#!/usr/bin/python
# coding=utf-8
"""Logs the temperature on a regular basis for visualization and statistics."""

import logging
import math

from . import common
from . import heating
from . import raspbee
from . import time_utils
from . import scheduling


class TemperatureLog:
    __instance = None
    LOGGER_NAME = 'temperature.log'

    @staticmethod
    def instance():
        """Returns the singleton."""
        return TemperatureLog.__instance

    @staticmethod
    def init_instance(cfg):
        """Initialize the singleton with the given configuration."""
        if TemperatureLog.__instance is None:
            TemperatureLog(cfg)
        return TemperatureLog.__instance


    def __init__(self, cfg):
        """Virtually private constructor, use TemperatureLog.init_instance() instead."""
        if TemperatureLog.__instance is not None:
            raise RuntimeError("TemperatureLog is a singleton!")
        TemperatureLog.__instance = self

# temperature_log = {
    # log_file = "logs/temperature.log";
    # rotation_when = "w6"; // Rotate log files on sunday...
    # rotation_interval = 1; // ... each week
    # rotation_backup_count = 104 // Up to two years - TODO shorter period!
    # update_interval_minutes = 5; // Poll sensors every X minutes
# };
        temp_cfg = cfg['temperature_log']

        # Set up rotating log file
        self._logger = logging.getLogger(type(self).LOGGER_NAME)
        formatter = logging.Formatter('%(message)s')
        file_handler = logging.handlers.TimedRotatingFileHandler(temp_cfg['log_file'], 
                    when=temp_cfg['rotation_when'], interval=int(temp_cfg['rotation_interval']),
                    backupCount=int(temp_cfg['rotation_backup_count']))
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        
        self._logger.addHandler(file_handler)
        self._logger.setLevel(logging.INFO)

        #TODO move periodic job to temp_log config (but then we need to skip it during serialization)

        # Compute size of circular buffer to store readings of the past 24 hours
        polling_interval_min = temp_cfg['update_interval_minutes']
        polling_job_label = 'Temperaturabfrage' #TODO Read from config?
        buffer_capacity = int(math.ceil(24*60/polling_interval_min))
        self._temperature_readings = common.circularlist(buffer_capacity)

        polling_job = scheduling.NonSerializableNonHeatingJob(polling_interval_min, 'never_used', polling_job_label).minutes.do(self.log_temperature)
        scheduling.HelheimrScheduler.instance().enqueue_job(polling_job)


    def recent_readings(self, index=0):
        """Returns the latest sensor reading (index=0), the previous one (index=1), older ones (index=...) or None, if it doesn't exist."""
        if index < len(self._temperature_readings):
            return self._temperature_readings[-1 - index] #TODO test reverse indexing of circularlist!
        return None


    def log_temperature(self):
        sensors = heating.Heating.instance().query_temperature()
        dt_local = time_utils.dt_now_local()
        if sensors is None:
            self._temperature_readings.append((dt_local, None))
            self._logger.log(logging.INFO, '{:s}'.format(time_utils.format(dt_local)))
        else:
            def _tocsv(s):
                return '{:s};{:s}'.format(s.display_name, s.temperature)

            self._temperature_readings.append((dt_local, [(s.display_name, s.temperature) for s in sensors]))
            self._logger.log(logging.INFO, '{:s};{:s}'.format(
                    time_utils.format(dt_local),
                    ';'.join(map(_tocsv, [s for s in sensors]))
                ))