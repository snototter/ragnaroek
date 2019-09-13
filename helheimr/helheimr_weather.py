from datetime import datetime
from dateutil import tz
import logging
import math
from pyowm import OWM

import helheimr_utils as hu

def degrees_to_compass(deg, num_directions=8):
    """:return: Compass direction (str, either 8 or 16) for the given angle (in degrees, 0 is north, 45 is east)."""
    if num_directions == 8:
        val = int((deg/45.0)+0.5)
        lookup = ["Nord", "Nordost", "Ost", "Südost", "Süd", "Südwest", "West", "Nordwest"]
        return lookup[(val % 8)]
    elif num_directions == 16:
        val = int((deg/22.5)+0.5)
        lookup = ["N","NNO","NO","ONO","O","OSO", "SO", "SSO","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        return lookup[(val % 16)]
    else:
        raise ValueError('You can only convert angle to 8 or 16 compass directions!')


#emoji list, supported by py-emoji. https://github.com/carpedm20/emoji/blob/master/emoji/unicode_codes.py
# https://stackoverflow.com/questions/4770297/convert-utc-datetime-string-to-local-datetime
def localize_utc_time(dt_object):
    from_zone = tz.gettz('UTC') # or tz.tzutc()
    to_zone = tz.gettz('Europe/Vienna') # or tz.tzlocal()
    utc = dt_object.replace(tzinfo=from_zone)
    return utc.astimezone(to_zone)


def weather_code_emoji(code):
    # if True:
    #     return ':cloud_with_lightning_and_rain: :cloud_with_lightning: :sun_behind_rain_cloud: :cloud_with_rain: :snowflake: :fog: :sunny: :partly_sunny: :sun_behind_small_cloud: :sun_behind_large_cloud: :cloud:'
    if code >= 200 and code < 300:
        # Thunderstorm
        return ':cloud_with_lightning_and_rain:' #':cloud_with_lightning:'
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
        return ':sunny:'
    elif code == 801:
        return ':partly_sunny:'
    elif code == 802:
        return ':sun_behind_small_cloud:'
    elif code == 803:
        return ':sun_behind_large_cloud:'
    elif code == 804:
        return ':cloud:'
        
    logging.getLogger().log(logging.ERROR, 'Weather code {} was not translated!'.format(code))
    return 'Wettercode {}'.format(code)

def temperature_emoji(t):
    # if True:
    #     return ':cold_face: :grimacing: :smiley: :sunglasses: :sweat: :hot_face:'
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
# emojis = [
#     ':cloud_with_lightning:', #done
#     ':partly_sunny:', 
#     ':sunny:',
#     ':cloud:',
#     ':cloud_with_lightning_and_rain:', 
#     ':cloud_with_rain:', 
#     ':cloud_with_snow:', 
#     ':sun_behind_cloud:', 
#     ':sun_behind_large_cloud:', 
#     ':sun_behind_rain_cloud:', 
#     ':sun_behind_small_cloud:',
#     ':sunrise:',
#     ':sunrise_over_mountains:',
#     ':sunset:',
#     ':thunder_cloud_and_rain:',
#     ':fog:',
#     ':foggy:',':hot_face:',':sweat:',':cold_face:']
# for em in emojis:
#     print(em, e(em, use_aliases=True))

def get_windchill(temperature, wind_speed):
    """Compute windchill temperature (input units °C and km/h)."""
    if temperature > 10.0:
        return temperature
    if wind_speed is None or wind_speed < 5:
        return temperature
    speed_pow = math.pow(wind_speed, 0.16)
    return 13.12 + 0.6215*temperature - 11.37*speed_pow + 0.3965*temperature*speed_pow


class WeatherReport:
    def __init__(self, weather=None):
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

        #TODO get rain, snow, change emoji during night
        self.clouds = w.get_clouds()
        # self.weather_emoji = weather_code_emoji(self.weather_code)
        rain = w.get_rain()
        # if rain:
        #     self.rain = rain['3h']
        #     # TODO!!

        # snow = w.get_snow()
        # if snow:
        #     self.snow = snow['3h'] 
        #     # TODO!!

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

        self.humidity = w.get_humidity() # int
        press = w.get_pressure()
        if press is not None and 'press' in press:
            self.atmospheric_pressure = press['press'] # dict
        
        self.sunrise_time = hu.datetime_as_local(w.get_sunrise_time(timeformat='date'))
        self.sunset_time = hu.datetime_as_local(w.get_sunset_time(timeformat='date'))
        

    def format_message(self, use_markdown=True, use_emoji=True):
        lines = list()
        lines.append('{}Wetterbericht:{}'.format(
                '*' if use_markdown else '',
                '*' if use_markdown else ''
            ))
        lines.append('{:s}{:s}, {:s}\u200a°'.format(
                self.detailed_status,
                ' ' + weather_code_emoji(self.weather_code) if use_emoji else '',
                hu.format_num('.1f', self.temperature, use_markdown),
            ))
        lines.append('Temperaturverlauf: {:s}-{:s}\u200a°{:s}'.format(
                hu.format_num('d', int(self.temperature_range['min']), use_markdown),
                hu.format_num('d', int(self.temperature_range['max']), use_markdown),
                ' ' + temperature_emoji((self.temperature_range['min'] + self.temperature_range['max']) / 2.0) if use_emoji else ''
            ))
        windchill = int(get_windchill(self.temperature, self.wind['speed']))
        if int(self.temperature) > windchill:
            lines.append('Gefühlte Temperatur: {:s}\u200a°{:s}'.format(
                    hu.format_num('d', windchill, use_markdown),
                    ' ' + temperature_emoji(windchill) if use_emoji else ''
                ))
        lines.append('') # Will be joined with a newline

        lines.append('Bewölkung: {}\u200a%'.format(hu.format_num('d', self.clouds, use_markdown)))
        lines.append('Luftfeuchte: {}\u200a%'.format(hu.format_num('d', self.humidity)))
        if self.atmospheric_pressure is not None:
            lines.append('Luftdruck: {}\u200ahPa'.format(hu.format_num('d', self.atmospheric_pressure)))
        if self.rain is not None:
            lines.append('Niederschlag: TODO')
        if self.snow is not None:
            lines.append('Schneefall: TODO')
        if self.wind is not None:
            lines.append('Wind: {}\u200akm/h{}'.format(
                    self.wind['speed'],
                    ' aus {}'.format(degrees_to_compass(self.wind['direction'])) if 'direction' in self.wind else ''
                ))
        lines.append('') # Will be joined with a newline

        lines.append('Sonnenaufgang: {:s}'.format(self.sunrise_time.strftime('%H:%m')))
        lines.append('Sonnenuntergang: {:s}'.format(self.sunset_time.strftime('%H:%m'))) # TODO check after Daylight Savings Time (Zeitumstellung!)

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


class WeatherForecastOwm:
    def __init__(self, config):
        self.owm = OWM(API_key=config['openweathermap']['api_token'],
            language='de', version='2.5')
        # self.city_id = config['openweathermap']['city_id']
        self.latitude = config['openweathermap']['latitude']
        self.longitude = config['openweathermap']['longitude']

    def query(self):
        # Either query by city ID or lat/lon
        # obs = self.owm.weather_at_id(self.city_id)
        obs = self.owm.weather_at_coords(self.latitude, self.longitude)
        w = obs.get_weather()
        return WeatherReport(w)


if __name__ == '__main__':
    wcfg = hu.load_configuration('configs/owm.cfg')
    weather_service = WeatherForecastOwm(wcfg)
    print(weather_service.query().format_message(True, True))
    