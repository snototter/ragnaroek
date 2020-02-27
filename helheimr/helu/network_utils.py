#!/usr/bin/python
# coding=utf-8


import os
import logging
import requests
import subprocess
import traceback

from . import heating
from . import raspbee
from . import telegram_bot

# TODO 
# * Replace network check (ping) by more efficient socket approach https://stackoverflow.com/a/33117579
# * exception handling in hel (e.g. all initializations upon (re)start)
# * reconnect telegram: journalctl --since "2 hours ago" -u helheimr-heating.service | grep telegram.error.NetworkError

def safe_http_get(url, headers=None, params=None, timeout=2.0, verify=True):
    """
    Performs a GET request at the given url (string) with the given headers and parameters
    and returns the response if one was received within timeout (float) seconds. Otherwise,
    returns None.
    """
    try:
        if headers is None:
            if params is None:
                r = requests.get(url, timeout=timeout, verify=verify)
            else:
                r = requests.get(url, params=params, timeout=timeout, verify=verify)
        else:
            if params is None:
                r = requests.get(url, headers=headers, timeout=timeout, verify=verify)
            else:
                r = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify)
        return r
    except:
        err_msg = traceback.format_exc(limit=3)
        logging.getLogger().error("Error HTTP GETting from '{}':\n{}".format(url, err_msg))
        return None


def http_get_request(url, timeout=2.0):
    """
    Performs a GET request at the given url (string) and returns the response if one
    was received within timeout (float) seconds. Otherwise, returns None.
    """
    return safe_http_get(url, None, None, timeout)
    # try:
    #     r = requests.get(url, timeout=timeout)
    #     return r
    # except:
    #     err_msg = traceback.format_exc(limit=3)
    #     logging.getLogger().error("Error HTTP GETting from '{}':\n{}".format(url, err_msg))
    #     return None


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
    hosts = [
        '1.0.0.1',  # Cloudflare DNS (usually fastest ping for me)
        '1.1.1.1',  # Also Cloudfare
        '8.8.8.8',  # Google DNS
        '8.8.8.4']  # Google again
    for host in hosts:
        if ping(host, timeout):
            return True
    return False


class ConnectionTester:
    __instance = None
    API_NAME_DECONZ = 'deCONZ API'  # Used as dict key and for display/reporting status

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

        # Collect hosts we rely on (weather service, telegram, local IPs, etc.)
        self._known_hosts_local = self.__load_known_hosts(cfg['control']['network']['local'])
        self._known_hosts_internet = self.__load_known_hosts(cfg['control']['network']['internet'])

        # TODO Add service URLs if needed
        self._known_service_urls = {
            'Telegram API': telegram_bot.get_bot_url(cfg['telegram']),
            'deCONZ API': raspbee.get_api_url(cfg['control'])
        }

    def __load_known_hosts(self, libconf_attr_dict):
        """Load hosts from configuration file - use parameter name as dictionary key."""
        return {k: libconf_attr_dict[k] for k in libconf_attr_dict}

    def list_known_connection_states(self, use_markdown=True):
        """Returns a multi-line string listing all known connections and their availability (ping, http get, etc.)"""
        msg = list()
        all_online = True
        # Check connectivity:
        msg.append('*Netzwerk/Services:*')
        # Home network
        for name, host in self._known_hosts_local.items():
            reachable = ping(host)
            msg.append('\u2022 {} [LAN] ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
            all_online = all_online and reachable
        # WWW
        for name, host in self._known_hosts_internet.items():
            reachable = ping(host)
            msg.append('\u2022 {} ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
            all_online = all_online and reachable

        deconz_api_available = False
        for name, url in self._known_service_urls.items():
            reachable = check_url(url)
            if name == type(self).API_NAME_DECONZ:
                # We list the deCONZ API state separately
                deconz_api_available = reachable
            else:
                msg.append('\u2022 {} ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
            all_online = all_online and reachable

        msg.append('')  # Empty line to separate text content
        if deconz_api_available:
            msg.append(heating.Heating.instance().query_deconz_status())
        else:
            msg.append('*Heizung:*\n\u2022 deCONZ API ist offline :bangbang:')
        return all_online, '\n'.join(msg)
