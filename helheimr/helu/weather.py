#!/usr/bin/python
# coding=utf-8

import logging
import math
import traceback

from pyowm import OWM

from . import common
from . import time_utils

#TODO nice-to-have: moon phase
# https://pypi.org/project/skyfield/
# skyfield.almanac.phase_angle fraction_illuminated
# https://pypi.org/project/skyfield-data/ or download the DE430 ephemeris manually?


def degrees_to_compass(deg, num_directions=8):
    """:return: Compass direction (str, either 8 or 16) for the given angle (in degrees, 0 is north, 45 is east)."""
    if num_directions == 8:
        val = int((deg/45.0)+0.5)
        # lookup = ["Nord", "Nordost", "Ost", "Südost", "Süd", "Südwest", "West", "Nordwest"]
        lookup = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]
        return lookup[(val % 8)]
    elif num_directions == 16:
        val = int((deg/22.5)+0.5)
        lookup = [
            "N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        return lookup[(val % 16)]
    else:
        raise ValueError('You can only convert angle to 8 or 16 compass directions!')


def weather_code_emoji(code, ref_time=None):
    """Return emoji for given weather code."""
    if code >= 200 and code < 300:
        # Thunderstorm
        return ':cloud_with_lightning_and_rain:'  # Or maybe replace by: :cloud_with_lightning: ':zap:'
    elif code >= 300 and code < 400:
        # Drizzle
        return ':sun_behind_rain_cloud:'
    elif code >= 500 and code < 600:
        # Rain
        if code == 511:
            # Freezing rain
            return ':cloud_with_rain: :snowflake:'
        return ':cloud_with_rain:'
    elif code >= 600 and code < 700:
        # Snow
        return ':snowflake:'
    elif code >= 700 and code < 800:
        # Atmospheric stuff (fog, mist, volcanic ashes)
        return ':fog:'
    elif code == 800:
        # Clear, check time-of-day
        if ref_time is None:
            ref_time = time_utils.t_now_local()
        if ref_time.hour >= 19 or ref_time.hour < 5:
            return ':full_moon:'
        return ':sunny:'
    elif code == 801:
        return ':partly_sunny:'
    elif code == 802:
        return ':sun_behind_small_cloud:'
    elif code == 803:
        return ':sun_behind_large_cloud:'
    elif code == 804:
        return ':cloud:'

    logging.getLogger().error('Weather code {} was not translated!'.format(code))
    return 'Wettercode {}'.format(code)


def temperature_emoji(t):
    """Returns emoji for given temperature."""
    if t < 0.0:
        return ':cold_face:'
    elif t < 10.0:
        return ':grimacing:'
    elif t < 18.0:
        return ':smiley:'
    elif t < 27.0:
        return ':sunglasses:'
    elif t < 30.0:
        return ':sweat:'
    else:
        return ':hot_face:'


def get_windchill(temperature, wind_speed):
    """Compute windchill temperature (input units °C and km/h)."""
    if temperature > 10.0:
        return temperature
    if wind_speed is None or wind_speed < 5:
        return temperature
    speed_pow = math.pow(wind_speed, 0.16)
    return 13.12 + 0.6215*temperature - 11.37*speed_pow + 0.3965*temperature*speed_pow


class Forecast:
    """Represents a weather forecast."""
    def __init__(self, three_hours_forecast):
        weathers = three_hours_forecast.get_forecast().get_weathers()[:9]

        def at_time(w):
            return time_utils.dt_as_local(w.get_reference_time(timeformat='date'))
        self._reports = [WeatherReport(w, at_time(w)) for w in weathers]

        # Extract temperature range
        temps = [w.temperature for w in self._reports]
        self._min_temp = int(math.floor(min(temps)))
        self._max_temp = int(math.ceil(max(temps)))

        # Get most prevalent weather status
        states = dict()
        emojis = dict()
        for r in self._reports:
            ds = r.detailed_status
            if ds in states:
                states[ds] += 1
            else:
                states[ds] = 1
            emojis[ds] = r.weather_emoji()
        sorted_states = [(s, e) for _, s, e in sorted(zip(states.values(), states.keys(), emojis.values()), reverse=True)]
        self._prevalent_detailed_status = sorted_states[0][0]
        self._prevalent_weather_emoji = sorted_states[0][1]

    def format_message(self, use_markdown=True, use_emoji=True, mark_day_break=True):
        lines = list()
        lines.append('{:s}Vorhersage:{:s}'.format(
            '*' if use_markdown else '', '*' if use_markdown else ''))
        lines.append('{:s}{:s}\n{:s} bis {:s}{:s}°'.format(
            self._prevalent_detailed_status,
            ' ' + self._prevalent_weather_emoji if use_emoji else '',
            common.format_num('d', self._min_temp, use_markdown=use_markdown),
            common.format_num('d', self._max_temp, use_markdown=use_markdown),
            '\u200a' if use_markdown else ''))
        for i in range(len(self._reports)):
            r = self._reports[i]
            if mark_day_break and i > 0 and r.reference_time.hour < self._reports[i-1].reference_time.hour:
                if use_markdown:
                    lines.append('\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7 Morgen \u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7\u00b7')
                else:
                    lines.append('~~~~~~~~~~ Morgen ~~~~~~~~~~')
            lines.append('{:02d}:00 {:s}'.format(r.reference_time.hour, r.teaser_message(use_markdown, use_emoji)))
        return '\n'.join(lines)


def _get_precipitation(weather_dict):
    if weather_dict:
        keys = ['1h', '3h']
        for k in keys:
            if k in weather_dict:
                return weather_dict[k]
    return None


class WeatherReport:
    """Represents the current weather report (i.e. current weather status)."""
    def __init__(self, weather=None, reference_time=None):
        self._detailed_status = None
        self._weather_code = None
        self._temperature_current = None
        self._temperature_range = None
        self._clouds = None
        self._rain = None
        self._wind = None
        self._snow = None
        self._humidity = None
        self._atmospheric_pressure = None
        self._sunset_time = None
        self._sunrise_time = None
        self._reference_time = reference_time
        if weather is not None:
            self.from_observation(weather)

    def from_observation(self, w):
        temp = w.get_temperature(unit='celsius')
        self.temperature = temp['temp']
        self.temperature_range = {
                'min': temp['temp_min'],
                'max': temp['temp_max']
            }

        self.detailed_status = w.get_detailed_status()
        self.weather_code = w.get_weather_code()

        self.clouds = w.get_clouds()
        self.rain = _get_precipitation(w.get_rain())
        self.snow = _get_precipitation(w.get_snow())

        wind = w.get_wind(unit='meters_sec')
        if wind:
            self.wind = {
                'speed': wind['speed'] * 3.6 if 'speed' in wind else None,
                'direction': wind['deg'] if 'deg' in wind else None
            }
        else:
            self.wind = {
                'speed': None,
                'direction': None
            }

        self.humidity = w.get_humidity()  # int
        press = w.get_pressure()
        if press is not None and 'press' in press:
            self.atmospheric_pressure = press['press']  # dict

        self.sunrise_time = time_utils.dt_as_local(w.get_sunrise_time(timeformat='date'))
        self.sunset_time = time_utils.dt_as_local(w.get_sunset_time(timeformat='date'))

    def teaser_message(self, use_markdown=True, use_emoji=True):
        msg = '{:s}{:s}°{:s}'.format(
                common.format_num('.1f', self.temperature, use_markdown),
                '\u200a' if use_markdown else '',
                ' ' + weather_code_emoji(self.weather_code, self._reference_time) if use_emoji else '')

        if self.rain is not None:
            msg += ' {:s}{:s}mm'.format(
                common.format_num('.1f', self.rain, use_markdown),
                '\u200a' if use_markdown else '')

        if self.snow is not None:
            msg += ' {:s}{:s}mm Schnee'.format(
                common.format_num('.1f', self.snow, use_markdown),
                '\u200a' if use_markdown else '')

        if self.wind is not None and 'speed' in self.wind and self.wind['speed'] is not None:
            msg += ' {:d}{:s}km/h{:s}'.format(
                    int(math.ceil(self.wind['speed'])),
                    '\u200a' if use_markdown else '',
                    ' {:s}'.format(degrees_to_compass(self.wind['direction'])) if self.wind['direction'] is not None else '')
        return msg

    def format_message(self, use_markdown=True, use_emoji=True):
        lines = list()
        lines.append('{:s}Wetterbericht:{:s}'.format(
                '*' if use_markdown else '',
                '*' if use_markdown else ''
            ))
        lines.append('{:s}{:s}, {:s}{:s}°'.format(
                self.detailed_status,
                ' ' + weather_code_emoji(self.weather_code, self._reference_time) if use_emoji else '',
                common.format_num('.1f', self.temperature, use_markdown),
                '\u200a' if use_markdown else ''
            ))
        if self.wind is not None and self.wind['speed'] is not None:
            windchill = int(get_windchill(self.temperature, self.wind['speed']))
            if int(self.temperature) > windchill:
                lines.append('Gefühlte Temperatur: {:s}{:s}°{:s}'.format(
                        common.format_num('d', windchill, use_markdown),
                        '\u200a' if use_markdown else '',
                        ' ' + temperature_emoji(windchill) if use_emoji else ''
                    ))
        lines.append('')  # Will be joined with a newline

        lines.append('Bewölkung: {:s}{:s}%'.format(
            common.format_num('d', self.clouds, use_markdown),
            '\u200a' if use_markdown else ''))

        lines.append('Luftfeuchte: {:s}{:s}%'.format(
            common.format_num('d', self.humidity, use_markdown),
            '\u200a' if use_markdown else ''))

        if self.atmospheric_pressure is not None:
            lines.append('Luftdruck: {:s}{:s}hPa'.format(
                common.format_num('d', self.atmospheric_pressure, use_markdown),
                '\u200a' if use_markdown else ''))

        if self.rain is not None:
            lines.append('Niederschlag: {:s}{:s}mm'.format(
                common.format_num('.1f', self.rain, use_markdown),
                '\u200a' if use_markdown else ''))

        if self.snow is not None:
            lines.append('Schneefall: {:s}{:s}mm'.format(
                common.format_num('.1f', self.snow, use_markdown),
                '\u200a' if use_markdown else ''))

        if self.wind is not None and self.wind['speed'] is not None:
            lines.append('Wind: {:s}{:s}km/h{:s}'.format(
                    common.format_num('.1f', self.wind['speed'], use_markdown),
                    '\u200a' if use_markdown else '',
                    ' aus {}'.format(degrees_to_compass(self.wind['direction'])) if self.wind['direction'] is not None else ''
                ))
        lines.append('')  # Will be joined with a newline

        lines.append('Sonnenaufgang: {:s}'.format(self.sunrise_time.strftime('%H:%m')))
        lines.append('Sonnenuntergang: {:s}'.format(self.sunset_time.strftime('%H:%m')))
        return '\n'.join(lines)

    @property
    def detailed_status(self):
        return self._detailed_status

    @detailed_status.setter
    def detailed_status(self, value):
        self._detailed_status = value

    @property
    def weather_code(self):
        return self._weather_code

    @weather_code.setter
    def weather_code(self, value):
        self._weather_code = value

    def weather_emoji(self):
        return weather_code_emoji(self._weather_code, self._reference_time)

    @property
    def temperature(self):
        return self._temperature_current

    @temperature.setter
    def temperature(self, value):
        self._temperature_current = value

    @property
    def temperature_range(self):
        return self._temperature_range

    @temperature_range.setter
    def temperature_range(self, minmax):
        self._temperature_range = minmax

    @property
    def clouds(self):
        return self._clouds

    @clouds.setter
    def clouds(self, value):
        self._clouds = value

    @property
    def rain(self):
        return self._rain

    @rain.setter
    def rain(self, value):
        self._rain = value

    @property
    def wind(self):
        return self._wind

    @wind.setter
    def wind(self, value):
        self._wind = value

    @property
    def snow(self):
        return self._snow

    @snow.setter
    def snow(self, value):
        self._snow = value

    @property
    def humidity(self):
        return self._humidity

    @humidity.setter
    def humidity(self, value):
        self._humidity = value

    @property
    def atmospheric_pressure(self):
        return self._atmospheric_pressure

    @atmospheric_pressure.setter
    def atmospheric_pressure(self, value):
        self._atmospheric_pressure = value

    @property
    def sunrise_time(self):
        return self._sunrise_time

    @sunrise_time.setter
    def sunrise_time(self, value):
        self._sunrise_time = value

    @property
    def sunset_time(self):
        return self._sunset_time

    @sunset_time.setter
    def sunset_time(self, value):
        self._sunset_time = value

    @property
    def reference_time(self):
        return self._reference_time

    @reference_time.setter
    def reference_time(self, value):
        self._reference_time = value


class WeatherForecastOwm:
    __instance = None

    @staticmethod
    def instance():
        """Returns the singleton, use init_instance() before!"""
        return WeatherForecastOwm.__instance

    @staticmethod
    def init_instance(config):
        """Initialize the singleton."""
        if WeatherForecastOwm.__instance is None:
            WeatherForecastOwm(config)
        return WeatherForecastOwm.__instance

    def __init__(self, config):
        """Virtually private constructor."""
        if WeatherForecastOwm.__instance is not None:
            raise RuntimeError("WeatherForecastOwm is a singleton!")
        WeatherForecastOwm.__instance = self

        self._owm = OWM(API_key=config['openweathermap']['api_token'],
            language='de', version='2.5')
        self._city_id = config['openweathermap']['city_id']
        self._city_name = config['openweathermap']['city_name']
        self._latitude = config['openweathermap']['latitude']
        self._longitude = config['openweathermap']['longitude']

    def report(self):
        """Return the current weather report."""
        try:
            obs = self._owm.weather_at_coords(self._latitude, self._longitude)
            w = obs.get_weather()
            return WeatherReport(w)
        except:
            logging.getLogger().error('[WeatherForecastOwm] Error querying OpenWeatherMap current weather:\n' + traceback.format_exc())
            return None

    def forecast(self):
        """Return the current weather forecast."""
        try:
            # Forecast(self._owm.three_hours_forecast(self._city_name)) # city name must be a string: "city,countrycode"!
            return Forecast(self._owm.three_hours_forecast_at_coords(self._latitude, self._longitude))
        except:
            logging.getLogger().error('[WeatherForecastOwm] Error querying OpenWeatherMap forecast:\n' + traceback.format_exc())
            return None


def demo(cfg_file='../configs/owm.cfg'):
    """Exemplary usage."""
    #TODO try without internet connection
    wcfg = common.load_configuration(cfg_file)
    weather_service = WeatherForecastOwm.init_instance(wcfg)
    print(weather_service.report().format_message(True, True))  # Note that the query may return None!


if __name__ == '__main__':
    demo()
