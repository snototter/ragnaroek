import json
import logging
import requests

#TODO https://stackoverflow.com/questions/373335/how-do-i-get-a-cron-like-scheduler-in-python <== needed for controller

class PlugState:
    def __init__(self, display_name, deconz_plug):
        self.display_name = display_name
        self.name = deconz_plug['name']
        self.reachable = deconz_plug['state']['reachable']
        self.on = deconz_plug['state']['on']
    
    def __str__(self):
        return "_{:s}_ ist {:s}erreichbar und *{:s}*".format(self.display_name, '' if self.reachable else '*nicht* ', 'ein' if self.on else 'aus')
        #return "Plug '{:s}' is {:s}reachable and {:s}".format(self.name, '' if self.reachable else 'NOT ', 'on' if self.on else 'off')


class TemperatureState:
    def __init__(self, display_name, temperature, humidity, pressure):
        pass


""" Communication with the zigbee/raspbee (deconz REST API) gateway """
class DeconzWrapper:
    def __init__(self, cfg):
        # Deconz parameters
        self.gateway = cfg['raspbee']['deconz']['gateway']
        self.tcp_port = cfg['raspbee']['deconz']['port']
        self.token = cfg['raspbee']['deconz']['api_token']
        self.api_url = 'http://' + self.gateway + ':' + str(self.tcp_port) + '/api/' + self.token

        # Currently I don't want a generic approach but rather know 
        # exactly (hardcoded) which plugs I control programatically
        
        # Map deconz plug name to human-readable display name
        self.heater_plug_display_name_mapping = {
            cfg['raspbee']['heating']['plug_names']['flat'] : cfg['raspbee']['heating']['display_names']['flat'],
            cfg['raspbee']['heating']['plug_names']['basement'] : cfg['raspbee']['heating']['display_names']['basement'],
        }

        # Map deconz plug name to deconz ID
        self.heater_plug_raspbee_name_mapping = _map_deconz_plugs(cfg)


    def lookup_heater_display_name(self, raspbee_id):
        for lbl, rid in self.heater_plug_mapping.items():
            if rid == raspbee_id:
                return self.heater_plug_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    
    def _map_deconz_plugs(cfg):
        # Our 'smart' plugs are linked to the zigbee gateway as "lights"
        r = requests.get(self._api_url() + '/lights')
        lights = json.loads(r.content)
        logger = logging.getLogger()

        plug_names = [
            cfg['raspbee']['heating']['plug_names']['flat'],
            cfg['raspbee']['heating']['plug_names']['basement']
        ]
        mapping = dict()

        for raspbee_id, light in lights.items():
            if light['name'] in plug_names:
                logger.info('Mapping {:s} ({:s}) to RaspBee ID {}'.format(light['name'],
                    self.heater_plug_display_name_mapping[light['name']], raspbee_id))
                mapping[light['name']] = raspbee_id
        return mapping


    def query_heating(self):
        status = list()
        is_heating = False
        logger = logging.getLogger()
        for plug_lbl, plug_id in self.heater_plug_raspbee_name_mapping.items():
            r = requests.get(self._api_url() + '/lights/' + plug_id)
            state = PlugState(self.heater_plug_display_name_mapping[plug_lbl], json.loads(r.content))
            status.append(state)
            logger.info(state)
            is_heating = is_heating or state.on
        return is_heating, status


    def switch_light(self, light_id, turn_on):
        r = requests.put(self.api_url + '/lights/' + light_id + '/state', data='{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        if r.status_code != 200:
            return False, 'Fehler (HTTP {:d}) beim {:s}schalten von {:s}.\n'.format(r.status_code, 'Ein' if turn_on else 'Aus', self.lookup_heater_display_name(light_id))
        return True, '{:s} wurde {:s}geschaltet.\n'.format(self.lookup_heater_display_name(light_id), 'ein' if turn_on else 'aus')
            

    def turn_on(self):
        # Technically (or-relais), we only need to turn on one.
        # But to have a less confusing status report, turn all on:
        # _, plug_id = next(iter(self.heater_plug_mapping.items()))
        # self.switch_light(plug_id, True)
        success = True
        msg = ''
        for _, plug_id in self.heater_plug_mapping.items():
            s, m = self.switch_light(plug_id, True)
            success = success and s
            msg += m
        return success, msg


    def turn_off(self):
        # Since this is an or-relais, we need to turn off all heating plugs
        success = True
        msg = ''
        for _, plug_id in self.heater_plug_mapping.items():
            s, m = self.switch_light(plug_id, False)
            success = success and s
            msg += m
        return success, msg
