#!/usr/bin/python
# coding=utf-8

from emoji import emojize
import libconf
# import datetime
# from dateutil import tz
# try:
#     from collections.abc import Hashable
# except ImportError:
#     from collections import Hashable
# import functools
# import logging
# import re
# import time
# import threading
# import traceback
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


# https://stackoverflow.com/a/40784706
class circularlist(object):
    def __init__(self, size):
        self.index = 0
        self.size = size
        self._data = list()

    def append(self, value):
        if len(self._data) == self.size:
            self._data[self.index] = value
        else:
            self._data.append(value)
        self.index = (self.index + 1) % self.size

    def __getitem__(self, key):
        """Get element by index, relative to the current index"""
        if len(self._data) == self.size:
            return(self._data[(key + self.index) % self.size])
        else:
            return(self._data[key])

    def __repr__(self):
        """Return string representation"""
        return self._data.__repr__() + ' (' + str(len(self._data))+' items)'