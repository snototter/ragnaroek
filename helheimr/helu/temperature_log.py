#!/usr/bin/python
# coding=utf-8
"""Logs the temperature on a regular basis for visualization and statistics."""

import logging
import math
import scipy.stats

from . import common
from . import heating
from . import raspbee
from . import time_utils
from . import scheduling

def compute_temperature_trend(readings, time_steps=None):
    """Fits a least-squares line to the temperature readings (list-like, np.array, etc.) and
    returns the tuple (slope, r_squared)."""
    if len(readings) < 2:
        return None, None
    if time_steps is None:
        time_steps = range(len(readings))
    slope, intercept, r_value, p_value, std_err = scipy.stats.linregress(time_steps, readings)
    return slope, r_value**2


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
        buffer_hours = 24
        buffer_capacity = int(math.ceil(buffer_hours*60/polling_interval_min))
        self._temperature_readings = common.circularlist(buffer_capacity)
        self._num_readings_per_hour = int(math.ceil(60/polling_interval_min)) + 1 # one more to include the same minute, one hour ago

        polling_job = scheduling.NonSerializableNonHeatingJob(polling_interval_min, 'never_used', polling_job_label).minutes.do(self.log_temperature)
        scheduling.HelheimrScheduler.instance().enqueue_job(polling_job)

        # Map internal display names of temperature sensors to their abbreviations
        self._sensor_abbreviations = dict()
        _sname2display = dict()
        for k in cfg['raspbee']['temperature']['display_names']:
            sensor_name = cfg['raspbee']['temperature']['sensor_names'][k]
            display_name = cfg['raspbee']['temperature']['display_names'][k]
            abbreviation = cfg['raspbee']['temperature']['abbreviations'][k]
            _sname2display[sensor_name] = abbreviation
            self._sensor_abbreviations[display_name] = abbreviation

        self._table_ordering = [_sname2display[sn] for sn in cfg['raspbee']['temperature']['preferred_heating_reference']]
        
        logging.getLogger().info('[TemperatureLog] Initialized buffer for {:d} entries, one every {:d} min for {:d} hours.'.format(buffer_capacity, polling_interval_min, buffer_hours))
        logging.getLogger().info('[TemperatureLog] Scheduled job: "{:s}"'.format(str(polling_job)))


    def recent_readings(self, num_entries=None):
        """Returns the latest num_entries sensor readings, i.e. a
        tuple (time_stamp_local_timezone, readings), where the
        latter is None or a dict(abbreviation:temperature).
        If num_entries is None, readings from the past hour will
        be returned."""
        if num_entries is None:
            num_entries = self._num_readings_per_hour

        if num_entries < 1:
            raise ValueError('Number of retrieved entries must be >= 1!')

        # If there are no readings yet, try to populate the log:
        if len(self._temperature_readings) == 0:
            self.log_temperature()

        num_entries = min(num_entries, len(self._temperature_readings))

        # Our circular list doesn't yet support slicing, so we do it the slow way:
        # tr[-num_entries:]
        ls = list()
        for i in range(num_entries):
            ls.append(self._temperature_readings[-1-i])
        return ls


    def format_table(self, num_entries=None, use_markdown=True):
        """Returns an ASCII table showing the last
        num_entries readings (or the last hour if
        num_entries is None).
               Wohn   KZ    SZ 
        -----------------------
        23:59  24.1  23.4  24.1
        """
        readings = self.recent_readings(num_entries)
        if len(readings) == 0:
            return 'Noch sind keine Temperaturaufzeichnungen verfügbar'

        msg = list()
        # Make the 'table' header:
        # ..:..  Col1   C2   Col3 ....
        def _header(h):
            if len(h) > 2:
                return '{:4s}'.format(h[:4])
            return ' {:3s}'.format(h)

        if use_markdown:
            msg.append('```')

        msg.append('       {:s}'.format('  '.join([_header(h) for h in self._table_ordering])))
        msg.append('-------' + '--'.join(['----' for _ in self._table_ordering]))

        # Table content
        for r in readings:
            dt_local, sensors = r
            if sensors is None:
                temp_str = '  '.join(['----' for _ in range(len(self._table_ordering))])
            else:
                temp_str = '  '.join(['{:4.1f}'.format(sensors[k]) for k in self._table_ordering])
            msg.append('{:02d}:{:02d}  {:s}'.format(dt_local.hour, dt_local.minute, temp_str))

        if use_markdown:
            msg.append('```')
        return '\n'.join(msg)


    def log_temperature(self):
        sensors = heating.Heating.instance().query_temperature()
        dt_local = time_utils.dt_now_local()
        if sensors is None:
            self._temperature_readings.append((dt_local, None))
            self._logger.log(logging.INFO, '{:s}'.format(time_utils.format(dt_local)))
        else:
            self._temperature_readings.append((dt_local, {self._sensor_abbreviations[s.display_name]: s.temperature for s in sensors}))

            def _tocsv(s):
                return '{:s};{:.1f}'.format(s.display_name, s.temperature)

            self._logger.log(logging.INFO, '{:s};{:s}'.format(
                    time_utils.format(dt_local),
                    ';'.join(map(_tocsv, [s for s in sensors]))
                ))