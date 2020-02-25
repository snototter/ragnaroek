#!/usr/bin/python
# coding=utf-8
"""The main controlling script."""

import logging
import logging.handlers
import os
import signal
import sys

# from helu import broadcasting
# from helu import common
# from helu import district_heating
# from helu import heating
# from helu import network_utils
# from helu import scheduling
# from helu import telegram_bot
# from helu import temperature_log

from balu import epaper

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'helheimr'))
from helu import common
from helu import weather



class Hel(object):
    def __init__(self):
        self._is_terminating = False
        self._logger = None
        self._epaper = None
        # self._scheduler = None
        # self._weather_service = None

    def control_heating(self):
        # Set up logging, see examples at:
        #   http://www.blog.pythonlibrary.org/2014/02/11/python-how-to-create-rotating-logs/
        # and the cookbook at https://docs.python.org/3/howto/logging-cookbook.html

        disk_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        # Suppress time (as it's added by journalctl by default)
        stream_formatter = logging.Formatter('%(levelname)s %(message)s')

        # Save to disk and rotate logs each sunday
        file_handler = logging.handlers.TimedRotatingFileHandler(
            'logs/breidablik.log', when="w6",
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
                logging.getLogger().info('[Baldr] Registered handler for signal {} #{}'.format(sig.name, sig.value))
            except OSError:
                logging.getLogger().error('[Baldr] Cannot register handler for signal {} #{}'.format(sig.name, sig.value))

        # Load configuration files
        ctrl_cfg = common.load_configuration('configs/ctrl.cfg')
        # telegram_cfg = common.load_configuration('configs/bot.cfg')
        owm_cfg = common.load_configuration('configs/owm.cfg')
        # schedule_job_list_path = 'configs/scheduled-jobs.cfg'

        # # Then, start the job scheduler
        # self._scheduler = scheduling.HelheimrScheduler.init_instance(
        #     ctrl_cfg, schedule_job_list_path)

        # Start the webserver for our e-ink display
        #TODO flask + flask-json

        # # Initialize weather service
        # self._weather_service = weather.WeatherForecastOwm.init_instance(owm_cfg)

        # # Run the event loops forever:
        # try:
        #     self._heating.run_blocking()
        #     # self._telegram_bot.idle()
        # except KeyboardInterrupt:
        #     self._logger.info("[Hel] Received keyboard interrupt")


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
