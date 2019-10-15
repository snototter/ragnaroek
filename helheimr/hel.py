#!/usr/bin/python
# coding=utf-8
"""The main controlling script."""

import logging
import os
import sys

from helu import broadcasting
from helu import common
from helu import heating
from helu import network_utils
from helu import scheduling
from helu import telegram_bot
from helu import temperature_log
from helu import weather



class Hel:
    def __init__(self):
        pass

    def control_heating(self):
        ## Set up logging
        # see examples at http://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
        # and the cookbook at https://docs.python.org/3/howto/logging-cookbook.html
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler = logging.handlers.TimedRotatingFileHandler('logs/helheimr.log', when="w6", # Rotate the logs each sunday
                    interval=1, backupCount=8)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(formatter)
        
        logging.getLogger().addHandler(stream_handler)
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().setLevel(logging.INFO)
        self._logger = logging.getLogger() # Adjust the root logger

        # Load configuration files
        ctrl_cfg = common.load_configuration('configs/ctrl.cfg')
        telegram_cfg = common.load_configuration('configs/bot.cfg')
        owm_cfg = common.load_configuration('configs/owm.cfg')
        schedule_job_list_path = 'configs/scheduled-jobs.cfg'

        # self._weather_service = weather.WeatherForecastOwm.init_instance(owm_cfg)
        # self._weather_service.query()
        # if True:
        #     return

        # Start the heater/heating controller
        try:
            self._heating = heating.Heating.init_instance(ctrl_cfg)
        except Exception as e:
            self._logger.error('[Hel] Error while setting up heating system:\n{}'.format(e))
            raise e


        # Create telegram bot
        try:
            self._telegram_bot = telegram_bot.HelheimrBot(telegram_cfg)
        except Exception as e:
            self._logger.error('[Hel] Error while setting up telegram bot:\n{}'.format(e))
            raise e

        # Register telegram bot for message broadcasting
        broadcasting.MessageBroadcaster.instance().set_telegram_bot(self._telegram_bot)

        # Set up network connectivity tester
        network_utils.ConnectionTester.init_instance({'telegram': telegram_cfg, 
            'control': ctrl_cfg})

        # Then, start the job scheduler
        self._scheduler = scheduling.HelheimrScheduler.init_instance(ctrl_cfg, schedule_job_list_path)

        # Set up the temperature log (after the scheduler!)
        temperature_log.TemperatureLog.init_instance(ctrl_cfg)

        # Start the webserver for our e-ink display
        #TODO

        # Initialize weather service
        self._weather_service = weather.WeatherForecastOwm.init_instance(owm_cfg)

        # Now we can start the telegram bot    
        self._telegram_bot.start()
        
        # Run the event loops forever:
        try:
            self._heating.run_blocking()
            # self._telegram_bot.idle()
        except KeyboardInterrupt:
            self._logger.info("[Hel] Received keyboard interrupt")

        # Gracefully shut down
        self._logger.info("[Hel] Shutting down...")
        self._telegram_bot.shutdown()
        self._scheduler.shutdown()
        self._heating.shutdown()
        self._logger.info("[Hel] All sub-systems are on hold, good bye!")


if __name__ == '__main__':
    hel = Hel()
    hel.control_heating()