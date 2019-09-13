import json
import logging
import requests

#TODO https://stackoverflow.com/questions/373335/how-do-i-get-a-cron-like-scheduler-in-python <== needed for controller
#TODO decorator util: plug_state_to_telegram
#TODO make properties, add format_message methods
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
    def __init__(self, display_name, deconz_sensor):
        self.display_name = display_name
        self.name = deconz_sensor['name']
        self.humidity = None
        self.pressure = None
        self.temperature = None
        self.battery_level = deconz_sensor['config']['battery']
        
        state = deconz_sensor['state']
        if deconz_sensor['type'] == 'ZHATemperature': #'temperature' in state:
            self.temperature = state['temperature'] / 100.0
        elif deconz_sensor['type'] == 'ZHAHumidity': #'humidity' in state:
            self.humidity = state['humidity'] / 100.0
        elif deconz_sensor['type'] == 'ZHAPressure': #'pressure' in state:
            self.pressure = state['pressure']

    def __str__(self):
        #TODO str anpassen (None objects; viel zu lang)
        return '_{:s}_: {:.1f}°C bei {:.1f}% Luftfeuchte und {:d}hPa Luftdruck, Batteriestatus: {:d}%'.format(
            self.display_name, self.temperature, self.humidity, self.pressure, self.battery_level)

    def merge(self, other):
        if self.name != other.name:
            raise RuntimeError('Cannot merge different temperature sensors!')
        
        if self.humidity is None:
            self.humidity = other.humidity
        if self.pressure is None:
            self.pressure = other.pressure
        if self.temperature is None:
            self.temperature = other.temperature
        self.battery_level = min(self.battery_level, other.battery_level)
        return self


""" Communication with the zigbee/raspbee (deconz REST API) gateway """
class RaspBeeWrapper:
    def __init__(self, cfg):
        # Deconz parameters
        self.gateway = cfg['raspbee']['deconz']['gateway']
        self.tcp_port = cfg['raspbee']['deconz']['port']
        self.token = cfg['raspbee']['deconz']['api_token']
        self.api_url = 'http://' + self.gateway + ':' + str(self.tcp_port) + '/api/' + self.token

        # Currently I don't want a generic approach but rather know 
        # exactly (hardcoded) which plugs I control programatically
        
        ######## Plugs to actually control the heating
        # Map deconz plug name to human-readable display name
        self.heating_plug_display_name_mapping = {
            cfg['raspbee']['heating']['plug_names']['flat'] : cfg['raspbee']['heating']['display_names']['flat'],
            cfg['raspbee']['heating']['plug_names']['basement'] : cfg['raspbee']['heating']['display_names']['basement']
        }

        # Map deconz plug name to deconz ID
        self.heating_plug_raspbee_name_mapping = self._map_deconz_heating_plugs(cfg)

        ######## Temperature sensors
        # Map deconz sensor name to human-readable display name
        self.temperature_sensor_display_name_mapping = {
            cfg['raspbee']['temperature']['sensor_names']['living_room'] : cfg['raspbee']['temperature']['display_names']['living_room']
        }

        # Map deconz sensor name to deconz ID
        self.temperature_sensor_raspbee_name_mapping = self._map_deconz_temperature_sensors(cfg)


    def lookup_heating_display_name(self, raspbee_id):
        for lbl, rid in self.heating_plug_raspbee_name_mapping.items():
            if rid == raspbee_id:
                return self.heating_plug_raspbee_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    
    def lookup_temperature_display_name(self, raspbee_id):
        for lbl, rids in self.temperature_sensor_raspbee_name_mapping.items():
            if raspbee_id in rids:
                return self.temperature_sensor_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    
    def _map_deconz_heating_plugs(self, cfg):
        # Our 'smart' plugs are linked to the zigbee gateway as "lights"
        r = requests.get(self.api_url + '/lights')
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
                    self.heating_plug_display_name_mapping[light['name']], raspbee_id))
                mapping[light['name']] = raspbee_id
        return mapping


    def _map_deconz_temperature_sensors(self, cfg):
        # Each of our sensors is takes up 3 separate raspbee IDs (temperature, humidity, pressure)
        r = requests.get(self.api_url + '/sensors')
        sensors = json.loads(r.content)
        logger = logging.getLogger()

        sensor_names = [
            cfg['raspbee']['temperature']['sensor_names']['living_room']
        ]
        mapping = dict()

        for raspbee_id, sensor in sensors.items():
            s = sensor['name']
            if s in sensor_names:
                logger.info('Mapping {:s} ({:s}) to RaspBee ID {}'.format(s,
                    self.temperature_sensor_display_name_mapping[s], raspbee_id))
                if s in mapping:
                    mapping[s].append(raspbee_id)
                else:
                    mapping[s] = [raspbee_id]
        return mapping


    def query_heating(self):
        """:return: flag (True if heating currently heating), list of PlugState"""
        status = list()
        is_heating = False
        logger = logging.getLogger()
        for plug_lbl, plug_id in self.heating_plug_raspbee_name_mapping.items():
            r = requests.get(self.api_url + '/lights/' + plug_id)
            state = PlugState(self.heating_plug_display_name_mapping[plug_lbl], json.loads(r.content))
            status.append(state)
            logger.info(state)
            is_heating = is_heating or state.on
        return is_heating, status


    def query_temperature(self):
        status = list()
        logger = logging.getLogger()
        for sensor_lbl, sensor_ids in self.temperature_sensor_raspbee_name_mapping.items():
            merged_state = None
            for sensor_id in sensor_ids:
                r = requests.get(self.api_url + '/sensors/' + sensor_id)
                state = TemperatureState(self.temperature_sensor_display_name_mapping[sensor_lbl], json.loads(r.content))
                if merged_state is None:
                    merged_state = state
                else:
                    merged_state = merged_state.merge(state)
            status.append(merged_state)
            logger.info(merged_state)
        # status = merge_temperature_states(status)
        # logger.info('Merging sensor readings:')
        # logger.info(status)
        return status


    def switch_light(self, light_id, turn_on):
        r = requests.put(self.api_url + '/lights/' + light_id + '/state', 
            data='{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        if r.status_code != 200:
            return False, 'Fehler (HTTP {:d}) beim {:s}schalten von {:s}.\n'.format(
                r.status_code, 'Ein' if turn_on else 'Aus', self.lookup_heating_display_name(light_id))
        else:
            return True, '{:s} wurde {:s}geschaltet.\n'.format(self.lookup_heating_display_name(light_id), 
                'ein' if turn_on else 'aus')
            

    def turn_on(self):
        is_heating, _ = self.query_heating()
        if is_heating:
            return True, 'Heizung läuft schon.'
        # Technically (or-relais), we only need to turn on one.
        # But to have a less confusing status report, turn all on:
        # _, plug_id = next(iter(self.heater_plug_mapping.items()))
        # self.switch_light(plug_id, True)
        success = True
        msg = ''
        for _, plug_id in self.heating_plug_raspbee_name_mapping.items():
            s, m = self.switch_light(plug_id, True)
            success = success and s
            msg += m
        return success, msg


    def turn_off(self):
        is_heating, _ = self.query_heating()
        if not is_heating:
            return True, 'Heizung ist schon aus.'
        # Since this is an or-relais, we need to turn off all heating plugs
        success = True
        msg = ''
        for _, plug_id in self.heating_plug_raspbee_name_mapping.items():
            s, m = self.switch_light(plug_id, False)
            success = success and s
            msg += m
        return success, msg
