#!/usr/bin/python
# coding=utf-8

import os
import logging
import requests
import subprocess
import traceback
import logging


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



class ConnectionTester:
    __instance = None

    @staticmethod
    def instance():
        """Returns the singleton."""
        return ConnectionTester.__instance

    @staticmethod
    def init_instance(ctrl_cfg):
        if ConnectionTester.__instance is None:
            ConnectionTester(ctrl_cfg)
        return ConnectionTester.__instance        


    def __init__(self, cfg):
        """Virtually private constructor, use TemperatureLog.init_instance() instead."""
        if ConnectionTester.__instance is not None:
            raise RuntimeError("ConnectionTester is a singleton!")
        ConnectionTester.__instance = self

        #TODO store known hosts to query in _local, _internet


    def list_known_connection_states(self, use_markdown=True):
        # msg = list()
        # # Check connectivity:
        # msg.append('*Netzwerk:*')
        # # Home network
        # for name, host in self.known_hosts_local.items():
        #     reachable = hu.ping(host)
        #     msg.append('\u2022 {} [LAN] ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
        # # WWW
        # for name, host in self.known_hosts_internet.items():
        #     reachable = hu.ping(host)
        #     msg.append('\u2022 {} ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
        # # Also check telegram
        # reachable = hu.check_url(self.known_url_telegram_api)
        # msg.append('\u2022 Telegram API ist {}'.format('online' if reachable else 'offline :bangbang:'))
        # msg.append('') # Empty line to separate text content
        # # Query RaspBee state
        # reachable = hu.check_url(self.known_url_raspbee)
        # if reachable:
        #     msg.append(self.raspbee_wrapper.query_full_state())
        # else:
        #     msg.append('*Heizung:*\n\u2022 deCONZ API ist offline :bangbang:')
        return 'TODO no known connections yet'
        