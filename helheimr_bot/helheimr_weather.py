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
        