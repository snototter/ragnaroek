#!/usr/bin/python
# coding=utf-8
"""Logs the temperature on a regular basis for visualization and statistics."""

import logging

from . import common
from . import heating
from . import raspbee
from . import time_utils
from . import scheduling


class TemperatureLog:
    __instance = None

    @staticmethod
    def instance():
        """Returns the singleton."""
        if TemperatureLog.__instance is None:
            TemperatureLog(config)
        return TemperatureLog.__instance


    def __init__(self):
        """Virtually private constructor, use TemperatureLog.init_instance() instead."""
        if TemperatureLog.__instance is not None:
            raise RuntimeError("TemperatureLog is a singleton!")
        TemperatureLog.__instance = self

        # Set up rotating log file
        self._logger = logging.getLogger("temperature.log")
        formatter = logging.Formatter('%(message)s')
        file_handler = logging.handlers.TimedRotatingFileHandler('logs/temperature.log', when="w6", # Rotate the logs each sunday
                    interval=1, backupCount=104) # Keep up to two years TODO shorter period, we'll never going to check it anyways
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        
        self._logger.addHandler(file_handler)
        self._logger.setLevel(logging.INFO)

        # TODO Store the past 24 hours in a circular buffer
        self._temperature_readings = common.circularlist(24*12) # One reading every 5 minutes

    def log_temperature(self):
        sensors = heating.Heating.instance().query_temperature()
        temperatures = tuple([s.temperature for s in sensors])
        self._temperature_readings.append(temperatures)
        #TODO log sensor states (humidity)
        #self._logger.info('{:s};' + ';'.join(map(str, [tr for tr in readings])))
