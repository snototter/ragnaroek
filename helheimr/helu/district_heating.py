#!/usr/bin/python
# coding=utf-8
"""Our solar/district heating system can be 'boosted' on really cold days."""

import logging
# import threading

# from . import broadcasting
from . import common
from . import network_utils
# from . import controller
# from . import lpd433
# from . import raspbee
# from . import time_utils
# from . import scheduling
# from . import telegram_bot

DistrictHeatingRequest = common.enum(ECO=1, MEDIUM=2, HIGH=3, VERY_HIGH=4, TRANSITION=5)

class DistrictHeating:
    __instance = None

    
    @staticmethod
    def instance():
        """Returns the singleton."""
        return DistrictHeating.__instance


    @staticmethod
    def init_instance(config):
        """
        Initialize the singleton.

        :param config:      libconfig++ system configuration
        """
        if DistrictHeating.__instance is None:
            DistrictHeating(config)
        return DistrictHeating.__instance


    def __init__(self, config):
        """Virtually private constructor, use DistrictHeating.init_instance() instead."""
        if DistrictHeating.__instance is not None:
            raise RuntimeError("DistrictHeating is a singleton!")
        DistrictHeating.__instance = self

        # Load headers to replay the cURL requests
        dhcfg = config['district_heating']
        self._headers = dict()
        headers = dhcfg['http_headers']
        for k in headers:
            self._headers[k] = headers[k]

        # Prepare the button mapping
        self._buttons = dict()
        tmp_request_type = DistrictHeatingRequest()
        for request_type in [r for r in dir(DistrictHeatingRequest) if not r.startswith('__')]:
            self._buttons[getattr(tmp_request_type, request_type)] = dhcfg['button_{:s}'.format(request_type.lower())]

        # Parameters which need to be set properly to switch on district heating
        self._param_change = (dhcfg['param_name_change'], dhcfg['param_value_change'])
        self._param_name_button = dhcfg['param_name_button']

        # URLs of the district heating gateway
        self._url_change = dhcfg['url_change']
        self._url_query = dhcfg['url_query']

        #TODO remove
        self.start_heating(DistrictHeatingRequest.HIGH) # TODO separate telegram cmd teleheating/fernwaerme (menu: x is on/off, turn x,y,z, on for 1h)
        self.query_heating() # TODO include fernwaerme in /details cmd

        logging.getLogger().info('[DistrictHeating] Initialized district heating wrapper.')


    def get_buttons(self):
        """Returns the (sub-set of) buttons to control the district heating system."""
        return [
            ('Eco', DistrictHeatingRequest.ECO), #TODO remove
            ('55\u200a°', DistrictHeatingRequest.MEDIUM),
            ('60\u200a°', DistrictHeatingRequest.HIGH),
            ('65\u200a°', DistrictHeatingRequest.VERY_HIGH)
        ]


    def start_heating(self, request_type):
        """request_type is a DistrictHeatingRequest, specifying which physical button press should be simulated."""
        print('You requested', request_type, 'type:', type(request_type))
        params = (
            (self._param_name_button, self._buttons[request_type]),
            self._param_change
        )
        # response = network_utils.safe_http_get(self._url_change, self._headers, params) #TODO enable once we're done
        #TODO check response (if None => exception, else r.status_code should be 200)
        return False, 'Not implemented'


    def query_heating(self):
        #TODO query #.cgi, parse result, check which button was pressed and return DistrictHeatingRequest
        print('QUERY', self._url_query, self._headers, 'params = None')
        #TODO check requests.get() doc for params=None
        return None
