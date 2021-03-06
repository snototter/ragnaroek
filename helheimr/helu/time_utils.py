#!/usr/bin/python
# coding=utf-8

import datetime
from dateutil import tz


def dt_as_local(dt):
    """Convenience wrapper, converting the datetime object dt to local timezone."""
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
    """Parses a date string, convenience wrapper. Uses the same default
    formatstring as @see format()."""
    return datetime.datetime.strptime(s, fmt)


def local_time_as_utc(hour, minute, second):
    """Convert HH:MM:SS in localtime to UTC."""
    t_local = datetime.time(hour=hour, minute=minute, second=second, tzinfo=tz.tzlocal())
    dt_local = datetime.datetime.combine(datetime.datetime.today(), t_local, tzinfo=tz.tzlocal())
    return dt_local.astimezone(tz.tzutc()).timetz()


def time_as_local(t):
    """
    Returns the datetime.time t localized to the user's timezone.
    If it has no tzinfo, we assume it is UTC.
    """
    if t.tzinfo is None or t.tzinfo.utcoffset(dt_now()) is None:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=tz.tzutc())
    else:
        dt = datetime.datetime.combine(datetime.datetime.today(), t, tzinfo=t.tzinfo)
    return dt_as_local(dt).timetz()


def days_hours_minutes_seconds(td):
    """Convert datetime.timedelta to days, hours, minutes"""
    return td.days, td.seconds//3600, (td.seconds//60) % 60, td.seconds % 60


def days_hours_minutes_seconds_from_sec(seconds):
    """Convenience wrapper to @see days_hours_minutes_seconds()."""
    return days_hours_minutes_seconds(datetime.timedelta(seconds=seconds))


def format_timedelta(td, small_space=True):
    """Returns a simplified string representation of the datetime.timedelta object td."""
    days, hours, minutes, seconds = days_hours_minutes_seconds(td)
    s = '' if days == 0 else '{:d}{:s}d'.format(days, '\u200a' if small_space else ' ')
    if hours > 0:
        if len(s) > 0:
            s += ' '
        s += '{:d}{:s}h'.format(hours, '\u200a' if small_space else ' ')
    if minutes > 0:
        if len(s) > 0:
            s += ' '
        s += '{:d}{:s}min'.format(minutes, '\u200a' if small_space else ' ')
    if seconds > 0 or len(s) == 0:
        if len(s) > 0:
            s += ' '
        s += '{:d}{:s}sec'.format(seconds, '\u200a' if small_space else ' ')
    return s


def format_time(t):
    """Convert to local time zone and return str representation."""
    t = time_as_local(t)
    return t.strftime('%H:%M')


def ceil_dt(dt, delta):
    """Round the given datetime.datetime object up to the nearest datetime.timedelta."""
    # adapted from https://stackoverflow.com/a/32657466
    q, r = divmod(dt - datetime.datetime.min.replace(tzinfo=dt.tzinfo), delta)
    return (datetime.datetime.min.replace(tzinfo=dt.tzinfo) + (q + 1)*delta) if r else dt


def floor_dt(dt, delta):
    """Round the given datetime.datetime object down to the nearest datetime.timedelta."""
    q, r = divmod(dt - datetime.datetime.min.replace(tzinfo=dt.tzinfo), delta)
    return (datetime.datetime.min.replace(tzinfo=dt.tzinfo) + q*delta) if r else dt


def floor_dt_hour(dt):
    """Round the datetime down to the nearest hour."""
    return floor_dt(dt, datetime.timedelta(hours=1))


def ceil_dt_hour(dt):
    """Round the datetime up to the nearest hour."""
    return ceil_dt(dt, datetime.timedelta(hours=1))


def round_nearest(dt, delta):
    """Round the datetime to the nearest timedelta (e.g. 5 minutes, 2 hours, etc.)"""
    c = ceil_dt(dt, delta)
    f = floor_dt(dt, delta)
    dc = c - dt
    df = dt - f
    return c if dc < df else f
