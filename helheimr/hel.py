#!/usr/bin/python
# coding=utf-8
"""The main controlling script."""

import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys

from helu import broadcasting
from helu import common
from helu import heating
from helu import scheduling
from helu import telegram_bot



class Hel:
    def __init__(self):
        pass

    def control_heating(self):
        ## Set up logging
        # see examples at http://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
        # and the cookbook at https://docs.python.org/3/howto/logging-cookbook.html
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler = TimedRotatingFileHandler('logs/helheimr.log', when="w6", # Rotate the logs each sunday
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

        # TODO create a rotating log for temperature readings (create class with own logger, schedule periodic readings)

        # Load configuration files
        ctrl_cfg = common.load_configuration('configs/ctrl.cfg')
        telegram_cfg = common.load_configuration('configs/bot.cfg')
        owm_cfg = common.load_configuration('configs/owm.cfg')
        schedule_job_list_path = 'configs/scheduled-jobs.cfg'

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

        # Then, start the job scheduler
        self._scheduler = scheduling.HelheimrScheduler.init_instance(ctrl_cfg, schedule_job_list_path)

        # Start the webserver for our e-ink display
        #TODO

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

#TODO periodic jobs:
# Query & log temperature - make a singleton with circular buffer + rotating log (which can be queried from the e-ink display)
#TODO check internet connection - maybe also periodically
#TODO fix weather forecast

#TODO
        # if not hu.check_internet_connection():
        #     #TODO weather won't work, telegram neither - check what happens!
        #     #TODO add warning message to display
        #     self.logger.error('No internet connection!')
        # # else:
        # #     self.logger.info('Yes, WE ARE ONLINE!')

        # # Weather forecast/service wrapper
        # weather_cfg = hu.load_configuration('configs/owm.cfg')
        # self.weather_service = hw.WeatherForecastOwm(weather_cfg)

        # # Telegram bot for notifications and user input (heat on-the-go ;-)
        # bot_cfg = hu.load_configuration('configs/bot.cfg')
        # self.telegram_bot = hb.HelheimrBot(bot_cfg, self)
        # self.telegram_bot.start()

        # # Collect hosts we need to contact (weather service, telegram, local IPs, etc.)
        # self.known_hosts_local = self._load_known_hosts(ctrl_cfg['network']['local'])
        # self.known_hosts_internet = self._load_known_hosts(ctrl_cfg['network']['internet'])
        # self.known_url_telegram_api = 'https://t.me/' + bot_cfg['telegram']['bot_name']
        # self.known_url_raspbee = self.raspbee_wrapper.api_url

    # def _load_known_hosts(self, libconf_attr_dict):
    #     return {k:libconf_attr_dict[k] for k in libconf_attr_dict}

