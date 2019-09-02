import json
import logging
import requests

class PlugState:
    def __init__(self, deconz_plug):
        self.name = deconz_plug['name']
        self.reachable = deconz_plug['state']['reachable']
        self.on = deconz_plug['state']['on']
    
    def __str__(self):
        return "Plug '{:s}' is {:s}reachable and {:s}".format(self.name, '' if self.reachable else 'NOT ', 'on' if self.on else 'off')


""" Communication with the zigbee/raspbee (deconz REST API) gateway """
class DeconzWrapper:
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
        logger = logging.getLogger()
        for raspbee_id, light in lights.items():
            if light['name'] in plug_names:
                logger.info('Mapping {:s} to RaspBee id {}'.format(light['name'], raspbee_id))
                plug_mapping[light['name']] = raspbee_id

    def query_heating(self):
        status = list()
        logger = logging.getLogger()
        for _, plug_id in self.heater_plug_mapping.items():
            r = requests.get(self._api_url() + '/lights/' + plug_id)
            state = PlugState(json.loads(r.content))
            status.append(state)
            logger.info(state)
            #TODO return, create string/message or something
        return status

    def switch_light(self, light_id, turn_on):
        r = requests.put(self._api_url() + '/lights/' + light_id + '/state', data='{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        #TODO log request status!

    def turn_on(self):
        # Only need to turn on the first plug (there's an or-relais)
        _, plug_id = next(iter(self.heater_plug_mapping.items()))
        self.switch_light(plug_id, True)

    def turn_off(self):
        # Since this is an or-relais, we need to turn off all heating plugs
        for _, plug_id in self.heater_plug_mapping.items():
            self.switch_light(plug_id, False)
            

    def _api_url(self):
        return 'http://' + self.gateway + '/api/' + self.token