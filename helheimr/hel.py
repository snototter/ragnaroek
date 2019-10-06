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

class MessageBroadcaster:
    def __init__(self):
        self._telegram_bot = None


    def set_telegram_bot(self, bot):
        self._telegram_bot = bot


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
            logging.getLogger().error('[MessageBroadcaster] Telegram bot is not available to broadcast:\n\n' + telegram_msg + '\n')


class Hel:
    def __init__(self):
        pass

    def control_heating(self):
        ## Set up logging
        # see examples at http://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
        log_handler = TimedRotatingFileHandler('helheimr.log', when="m", 
                    interval=1, backupCount=5) # FIXME switch to days or weeks!
        logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(),
                        log_handler])
        self._logger = logging.getLogger() # Adjust the root logger

        
        # TODO create a rotating log for temperature readings (create class with own logger, schedule periodic readings)

        # Load configuration files
        ctrl_cfg = common.load_configuration('configs/ctrl.cfg')
        telegram_cfg = common.load_configuration('configs/bot.cfg')
        owm_cfg = common.load_configuration('configs/owm.cfg')
        schedule_cfg = common.load_configuration('configs/scheduled-jobs.cfg')

        # Start the heater/heating controller
        self._message_broadcaster = MessageBroadcaster()
        try:
            self._heating = heating.Heating.init_instance(ctrl_cfg, self._message_broadcaster)
        except Exception as e:
            self._logger.error('[Hel] Error while setting up heating system:\n{}'.format(e))
            raise e


        # Create telegram bot
        try:
            self._telegram_bot = telegram_bot.HelheimrBot(telegram_cfg)
        except Exception as e:
            self._logger.error('[Hel] Error while setting up telegram bot:\n{}'.format(e))
            raise e

        self._message_broadcaster.set_telegram_bot(self._telegram_bot)



        # Then, start the job scheduler
        #TODO

        # Start the webserver for our e-ink display
        #TODO

        # Now we can start the telegram bot    
        self._telegram_bot.start()
        #TODO join scheduler (?)
        # heating.instance().shutdown()

        # load configs
        # set up bot, server, scheduler, heating, weather forecast
        #TODO:
        #message_broadcaster = ...
        
        # controller = HelheimrController()
        try:
            self._heating.run_blocking()
            # self._telegram_bot.idle()
        except KeyboardInterrupt:
            self._logger.info("[Hel] Received keyboard interrupt")

        self._logger.info("[Hel] Shutting down...")
        self._telegram_bot.shutdown()
        self._heating.shutdown()
        self._logger.info("[Hel] All sub-systems are on hold, good bye!")




if __name__ == '__main__':
    hel = Hel()
    hel.control_heating()
