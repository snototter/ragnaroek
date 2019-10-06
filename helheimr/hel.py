#!/usr/bin/python
# coding=utf-8
"""The main controlling script."""

import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys

from helu import heating
from helu import common
from helu import telegram_bot
# from helu import

class Hel:
    def __init__(self):
        pass

    def control_heating(self):
        ## Set up logging
        # see examples at http://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
        logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        self._logger = logging.getLogger() # Adjust the root logger

        log_handler = TimedRotatingFileHandler('helheimr.log', when="m", 
                    interval=1, backupCount=5) # FIXME switch to days or weeks!
        self._logger.addHandler(log_handler)


        # TODO create a rotating log for temperature readings (create class with own logger, schedule periodic readings)

        # Load configuration files
        ctrl_cfg = common.load_configuration('configs/ctrl.cfg')
        telegram_cfg = common.load_configuration('configs/bot.cfg')
        owm_cfg = common.load_configuration('configs/owm.cfg')
        schedule_cfg = common.load_configuration('configs/scheduled-jobs.cfg')

        # Create telegram bot (but do not start it yet, as it 
        # tries to query the heating upon start up)
        #TODO self._telegram_bot = telegram.HelheimrBot(bot_cfg, self)
        self._telegram_bot = None

        # Start the heater/heating controller
        self._heating = heating.Heating.init_instance(ctrl_cfg, self)

        # Now we can start the telegram bot    
        #TODO self._telegram_bot.start()

        # Then, start the job scheduler
        #TODO

        # Start the webserver for our e-ink display
        #TODO

        #TODO join scheduler (?)
        # heating.instance().shutdown()

        # load configs
        # set up bot, server, scheduler, heating, weather forecast
        #TODO:
        #message_broadcaster = ...
        
        # controller = HelheimrController()
        try:
            #FIXME remove:
            # import datetime
            # self._heating.start_heating(heating.HeatingRequest.MANUAL, 'Horst', duration=datetime.timedelta(seconds=2))
            # import time
            # time.sleep(4)
            # self._heating.stop_heating('blablabings')
            self._heating.run_blocking()
        except KeyboardInterrupt:
            self._logger.info("[Hel] Received keyboard interrupt")
            
        self._heating.shutdown()
        self._logger.info("[Hel] Shut down gracefully, good bye!")



    def error(self, message):
        self.__broadcast_message(message, 'error')

    def warning(self, message):
        self.__broadcast_message(message, 'warning')

    def info(self, message):
        self.__broadcast_message(message, 'info')

    def __broadcast_message(self, text, msg_type):
        #TODO broadcast to display!!!
        if msg_type == 'info':
            telegram_msg = text
        elif msg_type == 'warning':
            telegram_msg = ':warning: ' + text
        elif msg_type == 'error':
            telegram_msg = ':bangbang: ' + text
        else:
            telegram_msg = 'Unknown message type ({}): {}'.format(msg_type, text)
            
        if self._telegram_bot is not None:
            self._telegram_bot.broadcast_message(telegram_msg)
        else:
            self._logger.error('[Hel] Telegram bot is not available to broadcast:\n\n' + telegram_msg + '\n')


if __name__ == '__main__':
    hel = Hel()
    hel.control_heating()
