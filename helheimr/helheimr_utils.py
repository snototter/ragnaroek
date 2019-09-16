#!/usr/bin/python
# coding=utf-8

import libconf
from emoji import emojize
import datetime
from dateutil import tz
try:
    from collections.abc import Hashable
except ImportError:
    from collections import Hashable
import functools
import logging
import os
import random
import re
import requests
import subprocess
import time
import threading
import traceback
# import urllib3

#TODO refactor into separate scripts (network, scheduling, controller, text)

#######################################################################
# Utilities
# def slurp_stripped_lines(filename):
#     with open(filename) as f:
#         return [s.strip() for s in f.readlines()]

# def load_api_token(filename='.api-token'):
#     return slurp_stripped_lines(filename)
#     #with open(filename) as f:
#         #f.read().strip()
#         #return [s.strip() for s in f.readlines()] 


# def load_authorized_user_ids(filename='.authorized-ids'):
#     return [int(id) for id in slurp_stripped_lines(filename)]

def emo(txt):
    """Simply wrapping emoji.emojize() since I often need/forget the optional parameter ;-)"""
    return emojize(txt, use_aliases=True)


def load_configuration(filename):
    """Loads a libconfig configuration file."""
    with open(filename) as f:
        return libconf.load(f)


def http_get_request(url, timeout=2.0):
    """
    Performs a GET request at the given url (string) and returns the response if one
    was received within timeout (float) seconds. Otherwise, returns None.
    """
    try:
        r = requests.get(url, timeout=timeout)
        return r
    except:
        err_msg = traceback.format_exc(limit=3)
        logging.getLogger().error("Error connecting to '{}':\n{}".format(url, err_msg))
        return None


def http_put_request(url, data, timeout=5.0):
    try:
        r = requests.put(url, data=data, timeout=timeout)
        return r
    except:
        err_msg = traceback.format_exc(limit=3)
        logging.getLogger().error("Error connecting to '{}':\n{}".format(url, err_msg))
        return None


def ping(host, timeout=2):
    """Returns True if the host (string) responds to ICMP requests within timeout (int) seconds."""
    # Ping 1 package with timeout 1 second
    with open(os.devnull, 'wb') as devnull:
        return subprocess.call(['ping', '-c', '1', '-w', str(timeout), host], stdout=devnull, stderr=subprocess.STDOUT) == 0


def check_url(url, timeout=2):
    """Returns true if the given URL (string) can be retrieved via GET."""
    return http_get_request(url, timeout) is not None


def check_internet_connection(timeout=2):
    """Pings common DNS server to check, if we are online."""
    hosts = ['1.0.0.1', # Cloudflare DNS (usually fastest ping for me)
        '1.1.1.1', # Also Cloudfare,
        '8.8.8.8', # Google DNS
        '8.8.8.4' # Google again
        ]
    for host in hosts:
        if ping(host, timeout):
            return True
    return False
    

#######################################################################
# Time stuff


def as_timezone(dt_object, tz_from, tz_to):
    if dt_object.tzinfo is None or dt_object.tzinfo.utcoffset(dt_object) is None:
        dt_object = dt_object.replace(tzinfo=tz_from)
    #TODO check if tzinfo matches tz_from!
    return dt_object.astimezone(tz_to)

def datetime_as_local(dt_object):
    return as_timezone(dt_object, tz.tzutc(), tz.tzlocal())


def datetime_as_utc(dt_object):
    """Convert datetime object from local timezone to UTC (for 
    scheduling, we have to take care of daylight savings time).
    """
    return as_timezone(dt_object, tz.tzlocal(), tz.tzutc())
    #     from_zone = tz.tzlocal() #tz.gettz('Europe/Vienna')


def time_as_utc(t):
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=tz.tzlocal())
    else:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=t.tzinfo)
    return datetime_as_utc(dt).timetz()


def time_as_local(t):
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=tz.tzutc())
    else:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=t.tzinfo)
    return datetime_as_local(dt).timetz()


def datetime_now():
    return datetime_as_utc(datetime.datetime.now())


def datetime_difference(dt_object_start, dt_object_end):
    """Converts times to UTC and returns the time delta."""
    return datetime_as_utc(dt_object_end) - datetime_as_utc(dt_object_start)


#######################################################################
## Schedulable jobs (based on https://github.com/dbader/schedule, but
## timezone aware and multi-threaded)
class ScheduleError(Exception):
    """Base schedule exception"""
    pass

class ScheduleValueError(ScheduleError):
    """Base schedule value error"""
    pass

class IntervalError(ScheduleValueError):
    """An improper interval was used"""
    pass

class CancelJob(object):
    """Can be returned from a job to unschedule itself."""
    pass

class Job(object):
    @staticmethod
    def every(interval=1):
        return Job(interval=interval)

    def __init__(self, interval):
        self.interval = interval    # pause interval * unit between runs
        self.job_func = None        # the job job_func to run
        self.unit = None            # time units, e.g. 'minutes', 'hours', ...
        self.at_time = None         # optional time at which this job runs
        self.last_run = None        # datetime of the last run
        self.next_run = None        # datetime of the next run
        self.period = None          # timedelta between runs, only valid for
        self.start_day = None       # Specific day of the week to start on
        self.tags = set()           # unique set of tags for the job
        self.worker_thread = None
        self.keep_running = True
        self.start_after_creation = False # If true, will be marked to be run directly after creation


    def __lt__(self, other):
        """Jobs are sortable based on the time they run next."""
        return self.next_run < other.next_run

    def __str__(self):
        return (
            "Job(every {} {}{}, "
            "do={}, "
            "args={}, "
            "kwargs={})"
        ).format(self.interval,
                 self.unit[-1] if self.interval == 1 else self.unit,
                 '' if self.at_time is None else self.at_time,
                 self.job_func.__name__,
                 self.job_func.args,
                 self.job_func.keywords)

    def __repr__(self):
        def format_time(t):
            return datetime_as_local(t).strftime('%Y-%m-%d %H:%M:%S') if t else '[never]'

        def is_repr(j):
            return not isinstance(j, Job)

        timestats = '(last run: %s, next run: %s)' % (
                    format_time(self.last_run), format_time(self.next_run))

        if hasattr(self.job_func, '__name__'):
            job_func_name = self.job_func.__name__
        else:
            job_func_name = repr(self.job_func)
        args = [repr(x) if is_repr(x) else str(x) for x in self.job_func.args]
        kwargs = ['%s=%s' % (k, repr(v))
                  for k, v in self.job_func.keywords.items()]
        call_repr = job_func_name + '(' + ', '.join(args + kwargs) + ')'

        if self.at_time is not None:
            return 'Every %s %s at %s do %s %s' % (
                   self.interval,
                   self.unit[:-1] if self.interval == 1 else self.unit,
                   time_as_local(self.at_time), call_repr, timestats)
        else:
            fmt = (
                'Every %(interval)s ' +
                '%(unit)s do %(call_repr)s %(timestats)s'
            )

            return fmt % dict(
                interval=self.interval,
                unit=(self.unit[:-1] if self.interval == 1 else self.unit),
                call_repr=call_repr,
                timestats=timestats
            )

    @property
    def is_running(self):
        return self.worker_thread is not None and self.keep_running

    @property
    def second(self):
        if self.interval != 1:
            raise IntervalError('Use seconds instead of second')
        return self.seconds

    @property
    def seconds(self):
        self.unit = 'seconds'
        return self

    @property
    def minute(self):
        if self.interval != 1:
            raise IntervalError('Use minutes instead of minute')
        return self.minutes

    @property
    def minutes(self):
        self.unit = 'minutes'
        return self

    @property
    def hour(self):
        if self.interval != 1:
            raise IntervalError('Use hours instead of hour')
        return self.hours

    @property
    def hours(self):
        self.unit = 'hours'
        return self

    @property
    def day(self):
        if self.interval != 1:
            raise IntervalError('Use days instead of day')
        return self.days

    @property
    def days(self):
        self.unit = 'days'
        return self

    @property
    def week(self):
        if self.interval != 1:
            raise IntervalError('Use weeks instead of week')
        return self.weeks

    @property
    def weeks(self):
        self.unit = 'weeks'
        return self

    @property
    def monday(self):
        if self.interval != 1:
            raise IntervalError('Use mondays instead of monday')
        self.start_day = 'monday'
        return self.weeks

    @property
    def tuesday(self):
        if self.interval != 1:
            raise IntervalError('Use tuesdays instead of tuesday')
        self.start_day = 'tuesday'
        return self.weeks

    @property
    def wednesday(self):
        if self.interval != 1:
            raise IntervalError('Use wednesdays instead of wednesday')
        self.start_day = 'wednesday'
        return self.weeks

    @property
    def thursday(self):
        if self.interval != 1:
            raise IntervalError('Use thursdays instead of thursday')
        self.start_day = 'thursday'
        return self.weeks

    @property
    def friday(self):
        if self.interval != 1:
            raise IntervalError('Use fridays instead of friday')
        self.start_day = 'friday'
        return self.weeks

    @property
    def saturday(self):
        if self.interval != 1:
            raise IntervalError('Use saturdays instead of saturday')
        self.start_day = 'saturday'
        return self.weeks

    @property
    def sunday(self):
        if self.interval != 1:
            raise IntervalError('Use sundays instead of sunday')
        self.start_day = 'sunday'
        return self.weeks

    @property
    def start_immediately(self):
        self.start_after_creation = True
        return self

    def tag(self, *tags):
        """
        Tags the job with one or more unique indentifiers.
        Tags must be hashable. Duplicate tags are discarded.
        :param tags: A unique list of ``Hashable`` tags.
        :return: The invoked job instance
        """
        if not all(isinstance(tag, Hashable) for tag in tags):
            raise TypeError('Tags must be hashable')
        self.tags.update(tags)
        return self

    def at(self, time_str):
        """
        Specify a particular time that the job should be run at.
        :param time_str: A string in one of the following formats: `HH:MM:SS`,
            `HH:MM`,`:MM`, `:SS`. The format must make sense given how often
            the job is repeating; for example, a job that repeats every minute
            should not be given a string in the form `HH:MM:SS`. The difference
            between `:MM` and `:SS` is inferred from the selected time-unit
            (e.g. `every().hour.at(':30')` vs. `every().minute.at(':30')`).
        :return: The invoked job instance
        """
        if (self.unit not in ('days', 'hours', 'minutes')
                and not self.start_day):
            raise ScheduleValueError('Invalid unit')
        if not isinstance(time_str, str):
            raise TypeError('at() should be passed a string')
        if self.unit == 'days' or self.start_day:
            if not re.match(r'^([0-2]\d:)?[0-5]\d:[0-5]\d$', time_str):
                raise ScheduleValueError('Invalid time format')
        if self.unit == 'hours':
            if not re.match(r'^([0-5]\d)?:[0-5]\d$', time_str):
                raise ScheduleValueError(('Invalid time format for'
                                          ' an hourly job'))
        if self.unit == 'minutes':
            if not re.match(r'^:[0-5]\d$', time_str):
                raise ScheduleValueError(('Invalid time format for'
                                          ' a minutely job'))
        time_values = time_str.split(':')
        if len(time_values) == 3:
            hour, minute, second = time_values
        elif len(time_values) == 2 and self.unit == 'minutes':
            hour = 0
            minute = 0
            _, second = time_values
        else:
            hour, minute = time_values
            second = 0
        if self.unit == 'days' or self.start_day:
            hour = int(hour)
            if not (0 <= hour <= 23):
                raise ScheduleValueError('Invalid number of hours')
        elif self.unit == 'hours':
            hour = 0
        elif self.unit == 'minutes':
            hour = 0
            minute = 0
        minute = int(minute)
        second = int(second)
        self.at_time = time_as_utc(datetime.time(hour, minute, second))
        return self

    def do(self, job_func, *args, **kwargs):
        """
        Specifies the job_func that should be called every time the
        job runs.
        Any additional arguments are passed on to job_func when
        the job runs.
        :param job_func: The function to be scheduled
        :return: The invoked job instance
        """
        self.job_func = functools.partial(job_func, *args, **kwargs)
        try:
            functools.update_wrapper(self.job_func, job_func)
        except AttributeError:
            # job_funcs already wrapped by functools.partial won't have
            # __name__, __module__ or __doc__ and the update_wrapper()
            # call will fail.
            pass
        self._schedule_next_run()
        return self

    @property
    def should_run(self):
        """
        :return: ``True`` if the job should be run now.
        """
        return datetime_now() >= self.next_run
    
    @property
    def should_be_removed(self):
        """Periodic jobs should not be removed"""
        return False

    def start(self):
        """Start the job thread and immediately reschedule this job."""
        if self.worker_thread is not None and self.keep_running:
            logging.getLogger().warn('This job is already running. I will ignore this additional start() request: {}'.format(self))
        else:    
            self.keep_running = True
            self.worker_thread = threading.Thread(target=self._run_blocking, daemon=True)
            self.worker_thread.start()
            self.last_run = datetime_now()
            self._schedule_next_run()

    def _run_blocking(self):
        self.job_func()
        self.keep_running = False

    def stop(self):
        if self.is_running:
            self.keep_running = False # Heating jobs overwrite this (they have a condition variable which notifies the worker thread and ensures termination via joining)

    def _schedule_next_run(self):
        """
        Compute the instant when this job should run next.
        """
        if self.unit not in ('seconds', 'minutes', 'hours', 'days', 'weeks'):
            raise ScheduleValueError('Invalid unit')

        interval = self.interval

        self.period = datetime.timedelta(**{self.unit: interval})
        if self.last_run is None and self.start_after_creation:
            # print('will start myself immediately!', self)
            self.next_run = datetime_now()
        else:
            self.next_run = datetime_now() + self.period
        if self.start_day is not None:
            if self.unit != 'weeks':
                raise ScheduleValueError('`unit` should be \'weeks\'')
            weekdays = (
                'monday',
                'tuesday',
                'wednesday',
                'thursday',
                'friday',
                'saturday',
                'sunday'
            )
            if self.start_day not in weekdays:
                raise ScheduleValueError('Invalid start day')
            weekday = weekdays.index(self.start_day)
            days_ahead = weekday - self.next_run.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            self.next_run += datetime.timedelta(days_ahead) - self.period
        if self.at_time is not None:
            if (self.unit not in ('days', 'hours', 'minutes')
                    and self.start_day is None):
                raise ScheduleValueError(('Invalid unit without'
                                          ' specifying start day'))
            kwargs = {
                'second': self.at_time.second,
                'microsecond': 0
            }
            if self.unit == 'days' or self.start_day is not None:
                kwargs['hour'] = self.at_time.hour
            if self.unit in ['days', 'hours'] or self.start_day is not None:
                kwargs['minute'] = self.at_time.minute
            self.next_run = self.next_run.replace(**kwargs)
            # If we are running for the first time, make sure we run
            # at the specified time *today* (or *this hour*) as well
            if not self.last_run:
                now = datetime_now()
                if (self.unit == 'days' and self.at_time > now.timetz() and
                        self.interval == 1):
                    self.next_run = self.next_run - datetime.timedelta(days=1)
                elif self.unit == 'hours' \
                        and self.at_time.minute > now.minute \
                        or (self.at_time.minute == now.minute
                            and self.at_time.second > now.second):
                    self.next_run = self.next_run - datetime.timedelta(hours=1)
                elif self.unit == 'minutes' \
                        and self.at_time.second > now.second:
                    self.next_run = self.next_run - \
                                    datetime.timedelta(minutes=1)
        if self.start_day is not None and self.at_time is not None:
            # Let's see if we will still make that time we specified today
            if (self.next_run - datetime_now()).days >= 7:
                self.next_run -= self.period


#######################################################################
## Basic controlling stuff

class OnOffController:
    """Bang bang controller with hysteresis."""
    def __init__(self):
        self.desired_value = None
        self.hysteresis_threshold = None
        self.prev_response = None

    
    def set_desired_value(self, desired_value):
        self.desired_value = desired_value


    def set_hysteresis(self, threshold):
        self.hysteresis_threshold = threshold


    def update(self, actual_value):
        if self.desired_value is None:
            logging.getLogger().error('OnOffController.update() called without setting a desired value first!')
            return False

        minv = self.desired_value if self.hysteresis_threshold is None else self.desired_value - self.hysteresis_threshold
        maxv = self.desired_value if self.hysteresis_threshold is None else self.desired_value + self.hysteresis_threshold

        response = False
        if actual_value < minv:
            response = True
        elif actual_value > maxv:
            response = False
        else:
            # Inside upper/lower threshold, keep doing what you did  
            if self.prev_response is None:
                response = False
            else:
                response = self.prev_response
        self.prev_response = response
        return response


#######################################################################
## Message formatting

# def value(value, default=''):
#     """Returns the value if not none, otherwise an empty string."""
#     return default if value is None else value

def format_num(fmt, num, use_markdown=True):
        s = '{:' + fmt + '}'
        if use_markdown:
            s = '`' + s + '`'
        return s.format(num)
