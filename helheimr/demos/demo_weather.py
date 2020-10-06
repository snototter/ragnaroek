import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from helu import common, weather

# This needs an actual owm.cfg with a properly configured API token
config = common.load_configuration(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'configs', 'owm.cfg'))
# Initialize the grabber
weather.WeatherForecastOwm.init_instance(config)
# Grab the weather report
report = weather.WeatherForecastOwm.instance().report()
forecast = weather.WeatherForecastOwm.instance().forecast()

show_markdown = False
show_emoji = True
print(report.format_message(use_markdown=show_markdown, use_emoji=show_emoji))
print()
print(forecast.format_message(use_markdown=show_markdown, use_emoji=show_emoji))
