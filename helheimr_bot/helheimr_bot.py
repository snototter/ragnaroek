#!/usr/bin/env python
"""
Telegram bot helheimr - controlling and querying our heating system.
"""

# import argparse
# import os
# import sys
import json
import libconf
import requests
import time

#TODOs:
#TODO use logging


#######################################################################
# Utilities
def slurp_stripped_lines(filename):
    with open(filename) as f:
        return [s.strip() for s in f.readlines()]

def load_api_token(filename='.api-token'):
    return slurp_stripped_lines(filename)
    #with open(filename) as f:
        #f.read().strip()
        #return [s.strip() for s in f.readlines()] 


def load_authorized_user_ids(filename='.authorized-ids'):
    return slurp_stripped_lines(filename)


def load_configuration(filename='helheimr.cfg'):
    with open(filename) as f:
        return libconf.load(f)


#######################################################################
# Communication with the zigbee/raspbee (deconz REST API) gateway
class RaspBeeWrapper:
    def __init__(self, token, config):
        self.gateway = config['raspbee']['gateway']
        self.token = token

        # Currently I don't want a generic approach but rather know 
        # exactly (hardcoded) which plugs I control programatically
        self.heater_plug_mapping = dict()
        self._map_plugs(self.heater_plug_mapping, [
            config['heater_plug_mappings']['tepidarium'],
            config['heater_plug_mappings']['flat']
            ])

    def _map_plugs(self, plug_mapping, plug_names):
        # Currently, I'm only using smart plugs which are linked to
        # the zigbee gateway as "lights"
        r = requests.get(self._api_url() + '/lights')
        lights = json.loads(r.content)
        for raspbee_id, light in lights.items():
            if light['name'] in plug_names:
                print('Mapping {:s} to RaspBee id {}'.format(light['name'], raspbee_id))
                plug_mapping[light['name']] = raspbee_id

    def query_heating(self):
        status = list()
        for plug_name, plug_id in self.heater_plug_mapping.items():
            r = requests.get(self._api_url() + '/lights/' + plug_id)
            light = json.loads(r.content)
            is_on = light['state']['on']
            is_reachable = light['state']['reachable']
            print('Plug {:s} is reachable ({}), is on ({})'.format(plug_name, is_reachable, is_on))

    def _api_url(self):
        return 'http://' + self.gateway + '/api/' + self.token


#######################################################################
# Main bot workflow

def main():
    api_token_telegram, api_token_raspbee = load_api_token()
    authorized_ids = load_authorized_user_ids()
    config = load_configuration()

    #print(api_token_telegram)
    #print(api_token_raspbee)
    print(authorized_ids)
    print(config)
    raspbee = RaspBeeWrapper(api_token_raspbee, config)

    for i in range(3):
        raspbee.query_heating()
        time.sleep(3)

    


if __name__ == '__main__':
    main()