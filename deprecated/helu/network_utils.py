#!/usr/bin/python
# coding=utf-8

import os
import logging
import requests
import subprocess
import traceback

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
        logging.getLogger().error("Error HTTP GETting from '{}':\n{}".format(url, err_msg))
        return None


def http_put_request(url, data, timeout=2.0):
    try:
        r = requests.put(url, data=data, timeout=timeout)
        return r
    except:
        err_msg = traceback.format_exc(limit=3)
        logging.getLogger().error("Error HTTP PUTting to '{}':\n{}".format(url, err_msg))
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