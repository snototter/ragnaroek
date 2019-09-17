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
