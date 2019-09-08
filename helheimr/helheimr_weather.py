from datetime import datetime
from dateutil import tz
import logging
from pyowm import OWM

def degrees_to_compass(deg):
    val = int((deg/45.0)+0.5)
    lookup = ["Nord", "Nordost", "Ost", "Südost", "Süd", "Südwest", "West", "Nordwest"]
    return lookup[(val % 8)]
    # val = int((deg/22.5)+0.5)
    # lookup = ["N","NNO","NO","ONO","O","OSO", "SO", "SSO","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    # return lookup[(val % 16)]

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
    elif t < 20.0:
        return ':smiley:'
    elif t < 30.0:
        return ':sunglasses:'
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

        forecast = list()
        temp = w.get_temperature(unit='celsius')
        forecast.append('{:s} {:s}, {:d}°C'.format(w.get_detailed_status(), weather_code_emoji(w.get_weather_code()), int(temp['temp'])))
        forecast.append('Temperaturverlauf: {:d}-{:d}°C {:s}\n'.format(int(temp['temp_min']), int(temp['temp_max']), temperature_emoji((temp['temp_min']+temp['temp_max'])/2.0)))
        forecast.append('Bewölkung: {} %'.format(w.get_clouds()))

        # if w.get_rain():
        #     forecast.append('')TODO
        # if w.get_snow():TODO
        wind = w.get_wind()
        if wind:
            forecast.append('Wind: {:s}{:.1f} km/h'.format(degrees_to_compass(wind['deg']) + ', ' if 'deg' in wind else '', wind['speed']*3.6))

        # sunrise_time = datetime.fromtimestamp(sunrise_timestamp)
        # pip install pytz, tzlocal
        # https://stackoverflow.com/questions/2720319/python-figure-out-local-timezone/17363006#17363006
        # print('Sunrise:', sunrise_time.strftime("%Y %m %d -- %H:%M:%S"))
        # print('Sunset:', sunset_time.strftime("%Y %m %d -- %H:%M:%S"))

        forecast.append('Rel. Feuchte: {} %'.format(w.get_humidity()))
        forecast.append('Luftdruck: {} hPa\n'.format(w.get_pressure()['press']))
        #TODO
        sunrise_time = localize_utc_time(w.get_sunrise_time(timeformat='date'))
        sunset_time = localize_utc_time(w.get_sunset_time(timeformat='date'))
        forecast.append('Sonnenaufgang: {:s}:{:s}'.format(sunrise_time.strftime('%H'), sunrise_time.strftime('%m')))
        forecast.append('Sonnenuntergang: {:s}:{:s}'.format(sunset_time.strftime('%H'), sunset_time.strftime('%m'))) # TODO check after Daylight Savings Time (Zeitumstellung!)

        print('\n'.join(forecast))

        forecaster = self.owm.three_hours_forecast("Graz,AT")
        f = forecaster.get_forecast()
        for weather in f:
            print (weather.get_reference_time('iso'),weather.get_status())

        return '*Wetterbericht:*\n' + '\n'.join(forecast)
        