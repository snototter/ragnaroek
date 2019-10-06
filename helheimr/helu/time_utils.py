#!/usr/bin/python
# coding=utf-8

import datetime
from dateutil import tz
import logging
import time

#######################################################################
# Time stuff

#######################################################################
# Hide time stuff
def dt_now():
    return datetime.datetime.now(tz=tz.tzutc())


def dt_offset(delta):
    """Returns now(UTC) + delta, which must be a datetime.timedelta object."""
    return dt_now() + delta


def format(dt, fmt="%Y-%m-%d %H:%M:%S %Z"):
    """Returns the string representation localized to the user's timezone."""
    return dt.astimezone(tz.tzlocal()).strftime(fmt)


def local_time_as_utc(hour, minute, second):
    t_local = datetime.time(hour=hour, minute=minute, second=second, tzinfo=tz.tzlocal())
    dt_local = datetime.datetime.combine(datetime.datetime.today(), t_local, tzinfo=tz.tzlocal())
    return dt_local.astimezone(tz.tzutc()).timetz()


def time_as_local(t):
    """
    Returns the datetime.time t localized to the user's timezone.
    If it has no tzinfo, we assume it is UTC.
    """
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=tz.tzutc())
    else:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=t.tzinfo)
    return dt.astimezone(tz.tzlocal()).timetz()






## TODO remove the rest?

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





def datetime_now():
    return datetime_as_utc(datetime.datetime.now())


def datetime_difference(dt_object_start, dt_object_end):
    """Converts times to UTC and returns the time delta."""
    return datetime_as_utc(dt_object_end) - datetime_as_utc(dt_object_start)