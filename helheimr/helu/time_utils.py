#!/usr/bin/python
# coding=utf-8

import datetime
from dateutil import tz
import logging
import time

#######################################################################
# Time stuff

def dt_as_local(dt):
    return dt.astimezone(tz.tzlocal())


def dt_now():
    """Current datetime in UTC"""
    return datetime.datetime.now(tz=tz.tzutc())


def dt_now_local():
    """Current datetime in local timezone"""
    return dt_as_local(dt_now())


def t_now():
    """Current time in UTC"""
    return dt_now().timetz()


def t_now_local():
    """Current time in local timezone"""
    return time_as_local(t_now())


def dt_offset(delta):
    """Returns now(UTC) + delta, which must be a datetime.timedelta object."""
    return dt_now() + delta


def format(dt, fmt="%Y-%m-%d %H:%M:%S %Z"):
    """Returns the string representation localized to the user's timezone."""
    return dt.astimezone(tz.tzlocal()).strftime(fmt)

def dt_fromstr(s, fmt="%Y-%m-%d %H:%M:%S %Z"):
    return datetime.datetime.strptime(s, fmt)


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
    return dt_as_local(dt).timetz()


def days_hours_minutes_seconds(td):
    """Convert datetime.timedelta to days, hours, minutes"""
    return td.days, td.seconds//3600, (td.seconds//60)%60, td.seconds%60


def format_timedelta(td):
    """Returns a simplified string representation of the datetime.timedelta object td."""
    days, hours, minutes, seconds = days_hours_minutes_seconds(td)
    s = '' if days == 0 else '{:d}\u200ad'.format(days)
    if hours > 0:
        if len(s) > 0:
            s += ' '
        s += '{:d}\u200ah'.format(hours)
    if minutes > 0:
        if len(s) > 0:
            s += ' '
        s += '{:d}\u200amin'.format(minutes)
    if seconds > 0 or len(s) == 0:
        if len(s) > 0:
            s += ' '
        s += '{:d}\u200asec'.format(seconds)
    return s


def format_time(t):
    """Convert to local time zone and return str representation."""
    t = time_as_local(t)
    return t.strftime('%H:%M')


# def date_str(delimiter=['','','-','',''], ):
#     """Returns a YYYY*MM*DD*hh*mm*ss string using the given delimiters.
#     Provide less delimiter to return shorter strings, e.g.
#     delimiter=['-'] returns YYYY-MM
#     delimiter=['',''] returns YYYYMMDD
#     etc.
#     """
#     now = datetime.datetime.now()
#     res_str = now.strftime('%Y')
#     month = now.strftime('%m')
#     day = now.strftime('%d')
#     hour = now.strftime('%H')
#     minute = now.strftime('%M')
#     sec = now.strftime('%S')
#     num_delim = len(delimiter)
#     if num_delim == 0:
#         return res_str
#     res_str += '{:s}{:s}'.format(delimiter[0], month)
#     if num_delim == 1:
#         return res_str
#     res_str += '{:s}{:s}'.format(delimiter[1], day)
#     if num_delim == 2:
#         return res_str
#     res_str += '{:s}{:s}'.format(delimiter[2], hour)
#     if num_delim == 3:
#         return res_str
#     res_str += '{:s}{:s}'.format(delimiter[3], minute)
#     if num_delim == 4:
#         return res_str
#     res_str += '{:s}{:s}'.format(delimiter[4], sec)
#     if num_delim > 5:
#         raise RuntimeError('Too many delimiter, currently we only support formating up until seconds')
#     return res_str

