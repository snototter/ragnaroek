#!/usr/bin/python
# coding=utf-8
"""Our solar/district heating system can be 'boosted' on really cold days."""

import datetime
from html.parser import HTMLParser
import logging
import re
import traceback

# from . import broadcasting
from . import common
from . import network_utils
# from . import controller
# from . import lpd433
# from . import raspbee
from . import time_utils
# from . import scheduling
# from . import telegram_bot

# regexp to extract numbers from strings taken from https://stackoverflow.com/questions/4289331/how-to-extract-numbers-from-a-string-in-python/4289415
def extract_integers(string):
    return [int(t) for t in re.findall(r'\d+', string)]


def extract_floats(string):
    return [float(t) for t in re.findall(r'[-+]?[.]?[\d]+(?:,\d\d\d)*[\.]?\d*(?:[eE][-+]?\d+)?', string)]


class DistrictHeatingQueryParser(HTMLParser):
    """The district heating system gateway provides a quite crappy website.
    This parser takes care of the *really* dirty work to translate a status
    query into into something we can use programmatically.
    """
    def __init__(self):
        super(DistrictHeatingQueryParser, self).__init__()
        #TODO register div_ids
        self._status = {
            'eco_status': None,
            'eco_time': None,
            'medium_status': None,
            'medium_time': None,
            'high_status': None,
            'high_time': None,
            'very_high_status': None,
            'very_high_time': None,
            'transition_status': None,
            'transition_time': None,

            'consumption_state': None,       # Verbrauch '?geschaltet'
            'consumption_temperature': None, # Verbrauch °C
            'consumption_power': None,       # Verbrauch kW
            'teleheating_temperature': None, # Herkunft Fernwärme °C
        }#TODO some power?

        self._store_data_to = None # Holds the key into self._status (is set upon starting tags)

        self._div_mapping = {
            'pos38': 'eco_status',
            'pos34': 'medium_status',
            'pos36': 'high_status',
            'pos37': 'very_high_status',
            'pos39': 'transition_status',

            'posTODO1': 'eco_time',
            'pos35': 'medium_time',
            'pos29': 'high_time',
            'pos31': 'very_high_time',
            'posTODO2': 'transition_time', # Couldn't find the corresponding div id (as it's not always shown)

            'pos42': 'consumption_state',
            'pos40': 'consumption_temperature',
            'pos41': 'consumption_power',
        }
        self._interesting_divs = self._div_mapping.keys()
        #TODO add system status? (solar panel state, speicher, verbrauch, etc)

    @property
    def status_dict(self):
        return self._status

    @property
    def teleheating_temperature(self):
        return self._status['teleheating_temperature']

    @property
    def consumption_state(self):
        return self._status['consumption_state']
    @property
    def consumption_temperature(self):
        return self._status['consumption_temperature']
    @property
    def consumption_power(self):
        return self._status['consumption_power']

    @property
    def eco_status(self):
        return self._status['eco_status']
    @property
    def eco_time(self):
        return self._status['eco_time']

    @property
    def medium_status(self):
        return self._status['medium_status']
    @property
    def medium_time(self):
        return self._status['medium_time']

    @property
    def high_status(self):
        return self._status['high_status']
    @property
    def high_time(self):
        return self._status['high_time']

    @property
    def very_high_status(self):
        return self._status['very_high_status']
    @property
    def very_high_time(self):
        return self._status['high_time']

    @property
    def transition_status(self):
        return self._status['transition_status']
    @property
    def transition_time(self):
        return self._status['transition_time']

    def format_message(self, use_markdown=True):
        msg = list()
        msg.append('{}Fernwärmestatus:{}'.format('*' if use_markdown else '', '*' if use_markdown else ''))
        if self.teleheating_temperature is not None:
            msg.append('\u2022 Fernwärme Eingang {}\u200a°'.format(
                common.format_num('.1f', self.teleheating_temperature, use_markdown)))

        if self.consumption_state is not None:
            #TODO rename all of these to something more explanatory (see if we find someone who knows what these terms actually mean ;-)
            msg.append('\u2022 Verbrauch ist {}'.format(
                'eingeschaltet bei {}\u200a°, {}\u200akW'.format(
                    common.format_num('.1f', self.consumption_temperature, use_markdown),
                    common.format_num('.1f', self.consumption_power, use_markdown)) \
                if self.consumption_state else 'ausgeschaltet'))

        if self.eco_status is not None:
            msg.append('\u2022 Eco ist {}'.format(
                'ein, Restzeit {:s}'.format(
                    time_utils.format_timedelta(datetime.timedelta(seconds=self.eco_time))) \
                if self.eco_status else 'aus')) # TODO eco time will be None as we don't know the correct div

        if self.medium_status is not None:
            msg.append('\u2022 Mittel 55\u200a° ist {}'.format(
                'ein, Restzeit {:s}'.format(
                    time_utils.format_timedelta(datetime.timedelta(seconds=self.medium_time))) \
                if self.medium_status else 'aus'))

        if self.high_status is not None:
            msg.append('\u2022 Hoch 60\u200a° ist {}'.format(
                'ein, Restzeit {:s}'.format(
                    time_utils.format_timedelta(datetime.timedelta(seconds=self.high_time))) \
                if self.high_status else 'aus'))

        if self.very_high_status is not None:
            msg.append('\u2022 Sehr hoch 65\u200a° ist {}'.format(
                'ein, Restzeit {:s}'.format(
                    time_utils.format_timedelta(datetime.timedelta(seconds=self.very_high_time))) \
                if self.very_high_status else 'aus'))

        if self.transition_status is not None:
            msg.append('\u2022 Übergang ist {}'.format(
                'ein, Restzeit {:s}'.format(
                    time_utils.format_timedelta(datetime.timedelta(seconds=self.transition_time))) \
                if self.transition_status else 'aus')) #TODO div is also not known!

        return '\n'.join(msg)
        


    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            div_id = None
            for attr in attrs:
                name, val = attr
                if name == 'id':
                    div_id = val
                    break
            if div_id in self._interesting_divs:
                self._store_data_to = self._div_mapping[div_id]
            else:
                self._store_data_to = None


    def handle_endtag(self, tag):
        self._store_data_to = None


    def handle_data(self, data):
        if self._store_data_to is None:
            return
        trimmed = data.strip()
        if self._store_data_to == 'consumption_state':
            self._status[self._store_data_to] = True if trimmed.lower() == 'ongeschaltet' else False # sic!

        elif self._store_data_to.endswith('_status'):
            # Need to parse an on/off string
            self._status[self._store_data_to] = True if trimmed.lower() == 'on' else False

        elif self._store_data_to.endswith('_time'):
            # Need to parse an "remaining time" string which should contain 'Xm Ys'
            times = extract_integers(trimmed)
            if len(times) == 2:
                self._status[self._store_data_to] = times[0] * 60 + times[1]
            elif len(times) == 1:
                self._status[self._store_data_to] = times[0]
            else:
                logging.getLogger().error('[DistrictHeatingQueryParser] Invalid remaining time string: "{:s}"'.format(trimmed))
                #TODO broadcast error

        elif self._store_data_to.endswith('_temperature') or \
            self._store_data_to.endswith('_power'):
            # Should be a float
            nums = extract_floats(trimmed.replace(',', '.')) # Even the decimal point for floats changes on this wonderful gateway website...
            if len(nums) == 1:
                self._status[self._store_data_to] = nums[0]
            else:
                logging.getLogger().error('[DistrictHeatingQueryParser] Invalid data string for a single float: "{:s}"'.format(trimmed))
                #TODO broadcast error

        else:
            #TODO implement others if needed
            pass


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
        try:
            request_type = int(request_type)
            btn_id = self._buttons[request_type]
        except:
            err_msg = traceback.format_exc(limit=3)
            return False, 'Vorlauftemperatur konnte keiner Adresse zugeordnet werden: {}'.format(err_msg)

        print('You requested', request_type, 'btn id:', btn_id)
        params = (
            (self._param_name_button, btn_id),
            self._param_change
        )
        # response = network_utils.safe_http_get(self._url_change, self._headers, params) #TODO enable once we're done
        #TODO check response (if None => exception, else r.status_code should be 200)
        return False, 'Not implemented'


    def query_heating(self, use_markdown=True):
        response = network_utils.safe_http_get(self._url_query, headers=self._headers)
        if response is None:
            return False, 'Netzwerkfehler bei der Fernwärmeabfrage'
        
        if response:
            query_parser = DistrictHeatingQueryParser()
            query_parser.feed(response.text)
            return True, query_parser.format_message(use_markdown=use_markdown)
        else:
            return False, 'Fehler bei der Fernwärmeabfrage, HTTP Status: {}'.format(response.status_code)
