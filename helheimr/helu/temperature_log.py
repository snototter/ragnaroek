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

        # Compute size of circular buffer to store readings of the past 24 hours
        polling_interval_min = temp_cfg['update_interval_minutes']
        polling_job_label = temp_cfg['job_label']
        buffer_capacity = int(math.ceil(24*60/polling_interval_min))
        self._temperature_readings = common.circularlist(buffer_capacity)

        polling_job = scheduling.NonSerializableNonHeatingJob(polling_interval_min, 'never_used', polling_job_label).minutes.do(self.log_temperature)
        scheduling.HelheimrScheduler.instance().enqueue_job(polling_job)

        logging.getLogger().info('[TemperatureLog] Initialized buffer for {:d} entries and scheduled job: "{:s}"'.format(buffer_capacity, str(polling_job)))

        # Map internal display names of temperature sensors to their abbreviations
        #TODO also load automagically from config in raspbee.py!
        self._sensor_abbreviations = dict()
        _sname2display = dict()
        for k in cfg['raspbee']['temperature']['display_names']:
            sensor_name = cfg['raspbee']['temperature']['sensor_names'][k]
            display_name = cfg['raspbee']['temperature']['display_names'][k]
            abbreviation = cfg['raspbee']['temperature']['abbreviations'][k]
            _sname2display[sensor_name] = abbreviation
            self._sensor_abbreviations[display_name] = abbreviation

        self._table_ordering = [_sname2display[sn] for sn in cfg['raspbee']['temperature']['preferred_heating_reference']]
        


    def recent_readings(self, num_entries=1):
        """Returns the latest num_entries sensor readings. A sensor reading 
        may also be None if the sensor was unavailable during query."""
        if num_entries < 1:
            raise ValueError('Number of retrieved entries must be >= 1!')
        num_entries = min(num_entries, len(self._temperature_readings))
        # Our circular list doesn't yet support slicing, so we do it the slow way:
        # tr[-num_entries:]
        ls = list()
        for i in range(num_entries):
            ls.append(self._temperature_readings[-1-i])
        return ls


    def format_table(self, num_entries):
        readings = self.recent_readings(num_entries)
        msg = list()
        # Make the 'table' header:
        # ..:..  Col1   C2   Col3 ....
        def _header(h):
            if len(h) > 2:
                return '{:4s}'.format(h[:4])
            return ' {:3s}'.format(h)
        msg.append('       {:s}'.format('  '.join([_header(h) for h in self._table_ordering])))

        # Table content
        for r in readings:
            dt_local, sensors = r
            if sensors is None:
                temp_str = '  '.join(['----' for _ in range(len(self._table_ordering))])
            else:
                temp_str = '  '.join(['{:4.1f}'.format(sensors[k]) for k in self._table_ordering])
            msg.append('{:02d}:{:02d}  {:s}'.format(dt_local.hour, dt_local.minute, temp_str))
        return '\n'.join(msg)


    def log_temperature(self):
        sensors = heating.Heating.instance().query_temperature()
        dt_local = time_utils.dt_now_local()
        if sensors is None:
            self._temperature_readings.append((dt_local, None))
            self._logger.log(logging.INFO, '{:s}'.format(time_utils.format(dt_local)))
        else:
            def _tocsv(s):
                return '{:s};{:.1f}'.format(s.display_name, s.temperature)

            self._temperature_readings.append((dt_local, {self._sensor_abbreviations[s.display_name]: s.temperature for s in sensors}))
            self._logger.log(logging.INFO, '{:s};{:s}'.format(
                    time_utils.format(dt_local),
                    ';'.join(map(_tocsv, [s for s in sensors]))
                ))