#!/usr/bin/python
# coding=utf-8
"""The main controlling script."""

import logging
import signal

from helu import broadcasting
from helu import common
from helu import district_heating
from helu import heating
from helu import network_utils
from helu import scheduling
from helu import telegram_bot
from helu import temperature_log
from helu import weather


class Hel(object):
    def __init__(self):
        self._is_terminating = False
        self._logger = None
        self._heating = None
        self._scheduler = None
        self._telegram_bot = None
        self._weather_service = None

    def control_heating(self):
        # Set up logging, see examples at:
        #   http://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
        # and the cookbook at https://docs.python.org/3/howto/logging-cookbook.html

        disk_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        # Suppress time (as it's added by journalctl by default)
        stream_formatter = logging.Formatter('%(levelname)s %(message)s')

        # Save to disk and rotate logs each sunday
        file_handler = logging.handlers.TimedRotatingFileHandler(
            'logs/helheimr.log', when="w6",
            interval=1, backupCount=8)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(disk_formatter)

        # Also log to stdout/stderr
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(stream_formatter)

        # Configure this application's root logger
        logging.getLogger().addHandler(stream_handler)
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().setLevel(logging.INFO)
        self._logger = logging.getLogger()

        # Register signal handler to be notified upon system shutdown:
        catchable_sigs = set(signal.Signals) - {signal.SIGKILL, signal.SIGSTOP}
        for sig in catchable_sigs:
            try:
                signal.signal(sig, self.__shutdown_signal)
                logging.getLogger().info('[Hel] Registered handler for signal {} #{}'.format(sig.name, sig.value))
            except OSError:
                logging.getLogger().error('[Hel] Cannot register handler for signal {} #{}'.format(sig.name, sig.value))

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

        # Set up the district heating wrapper
        try:
            district_heating.DistrictHeating.init_instance(ctrl_cfg)
        except Exception as e:
            self._logger.error('[Hel] Error while setting up district heating system:\n{}'.format(e))
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
        network_utils.ConnectionTester.init_instance(
            {'telegram': telegram_cfg, 'control': ctrl_cfg})

        # Then, start the job scheduler
        self._scheduler = scheduling.HelheimrScheduler.init_instance(
            ctrl_cfg, schedule_job_list_path)

        # Set up the temperature log (after the scheduler!)
        temperature_log.TemperatureLog.init_instance(ctrl_cfg)

        # Start the webserver for our e-ink display
        #TODO flask + flask-json

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

        self.__shutdown_gracefully()

    def __shutdown_signal(self, sig, frame):
        logging.getLogger().info('[Hel] Signal {} received - preparing shutdown.'.format(sig))
        self.__shutdown_gracefully()

    def __shutdown_gracefully(self):
        if self._is_terminating:
            return
        self._is_terminating = True
        # Gracefully shut down
        self._logger.info("[Hel] Shutting down...")
        self._telegram_bot.shutdown()
        self._scheduler.shutdown()
        self._heating.shutdown()
        self._logger.info("[Hel] All sub-systems are on hold, good bye!")


if __name__ == '__main__':
    hel = Hel()
    hel.control_heating()
