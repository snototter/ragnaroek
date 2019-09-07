from datetime import datetime
from pytz import timezone
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
    current = utc.astimezone(to_zone)

def weather_code_emoji(code):
    # Clear sky
    # Few clouds partly_sunny
    # Scattered clouds :cloud:
    # Broken clouds :cloud:
    # Shower rain (drizzle)
    # Rain >= 500, < 600 (except for 511, freezing rain: snow + rain icon!)
    # Thunderstorm code >= 200 and code < 300
    # Snow
    # Mist

    emojis = [':cloud_with_lightning:', 
        ':partly_sunny:', ':sunny:',
        ':cloud:',
        ':cloud_with_lightning_and_rain:', 
        ':cloud_with_rain:', 
        ':cloud_with_snow:', 
        ':sun_behind_cloud:', 
        ':sun_behind_large_cloud:', 
        ':sun_behind_rain_cloud:', 
        ':sun_behind_small_cloud:',
        ':sunrise:',
        ':sunrise_over_mountains:',
        ':sunset:',
        ':thunder_cloud_and_rain:',
        ':fog:',
        ':foggy:',':hot_face:',':sweat:',':cold_face:']
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
# logger = logging.getLogger()
# rain:        {'1h': 2.54}
# snow: {}
# wind: {'speed': 3.1, 'deg': 240}
# humidity: 87
# pressure: {'press': 1020, 'sea_level': None}
# {'temp': 14.14, 'temp_max': 15.0, 'temp_min': 13.0, 'temp_kf': None}
        # Either query by city ID or lat/lon
        # obs = self.owm.weather_at_id(self.city_id)
        obs = self.owm.weather_at_coords(self.latitude, self.longitude)
        w = obs.get_weather()

        forecast = list()
        temp = w.get_temperature(unit='celsius')
        forecast.append('{:s}, {:d} °C'.format(w.get_detailed_status(), int(temp['temp'])))
        forecast.append('Temperaturverlauf: {:d}-{:d} °C\n'.format(int(temp['temp_min']), int(temp['temp_max'])))
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
        sunrise_time = w.get_sunrise_time(timeformat='date')
        sunset_time = w.get_sunset_time(timeformat='date')
        forecast.append('Sonnenaufgang: {:s}:{:s} *TODO* stimmt nicht +2/+1'.format(sunrise_time.strftime('%H'), sunrise_time.strftime('%m')))
        forecast.append('Sonnenuntergang: {:s}:{:s} *TODO* stimmt nicht +2/+1'.format(sunset_time.strftime('%H'), sunset_time.strftime('%m')))

        return '*Wetterbericht:*\n' + '\n'.join(forecast)
        