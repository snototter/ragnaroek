#!/usr/bin/python
# coding=utf-8

import json
import logging
import requests
import traceback

import helu as hu

class PlugState:
    def __init__(self, display_name, deconz_plug):
        self.display_name = display_name
        self.name = deconz_plug['name']
        self.reachable = deconz_plug['state']['reachable']
        self.on = deconz_plug['state']['on']
    
    def __str__(self):
        return "{:s} ist {:s}erreichbar und {:s}".format(self.display_name, '' if self.reachable else '*nicht* ', 'ein' if self.on else 'aus')

    def format_message(self, use_markdown=True, detailed_information=False):
        txt = '{}{}{} ist '.format(
            '_' if use_markdown else '',
            self.display_name,
            '_' if use_markdown else ''
        )
        if self.reachable:
            txt += 'ein' if self.on else 'aus'
        if not self.reachable or detailed_information:
            txt += ' und '
            if not self.reachable:
                txt += '{}NICHT{} '.format(
                    '*' if use_markdown else '',
                    '*' if use_markdown else '')
            txt += 'erreichbar{}'.format(
                    '.' if self.reachable else (' :skull_and_crossbones::bangbang:' if use_markdown else '!'))
        else:
            txt += '.'
        return txt


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
        return '{:s}: {:.1f}°C bei {:.1f}% Luftfeuchte und {:d}hPa Luftdruck, Batteriestatus: {:d}%'.format(
            self.display_name, 
            -100 if self.temperature is None else self.temperature, 
            -100 if self.humidity is None else self.humidity, 
            -1000 if self.pressure is None else self.pressure, 
            -9999 if self.battery_level is None else self.battery_level)


    def merge(self, other):
        if self.name != other.name:
            raise RuntimeError('Cannot merge different temperature sensors!')
        
        if self.humidity is None:
            self.humidity = other.humidity
        if self.pressure is None:
            self.pressure = other.pressure
        if self.temperature is None:
            self.temperature = other.temperature
        
        if self.battery_level is None:
            self.battery_level = other.battery_level
        elif other.battery_level is not None:
            self.battery_level = min(self.battery_level, other.battery_level)
        return self


    def format_message(self, use_markdown=True, detailed_information=False):
        # hair space: U+200A, thin space: U+2009
        txt = '{}{}{}: {}\u200a°, {}\u200a%, {}\u200ahPa'.format(
                '_' if use_markdown else '',
                self.display_name,
                '_' if use_markdown else '',
                hu.format_num('.1f', self.temperature, use_markdown),
                hu.format_num('d', int(self.humidity), use_markdown),
                hu.format_num('d', self.pressure, use_markdown))

        if detailed_information or (self.battery_level is not None and self.battery_level < 20):
            txt += ', {}\u200a% Akku{:s}'.format(
                '?' if self.battery_level is None else hu.format_num('d', int(self.battery_level),
                use_markdown),
                ' :warning:' if use_markdown and (self.battery_level is not None and self.battery_level < 20) else '')
        return txt

    @staticmethod
    def merge_sensors(sensor_list):
        if len(sensor_list) == 0:
            return list()
        sorted_sensors = sorted(sensor_list, key=lambda s:s.name)
        merged = [sorted_sensors[0]]
        for i in range(1, len(sorted_sensors)):
            if sorted_sensors[i].name != merged[-1].name:
                merged.append(sorted_sensors[i])
            else:
                merged[-1] = merged[-1].merge(sorted_sensors[i])
        return merged



""" Communication with the zigbee/raspbee (deconz REST API) gateway """
class RaspBeeWrapper:
    def __init__(self, cfg):
        # Deconz parameters
        self._gateway = cfg['raspbee']['deconz']['gateway']
        self._tcp_port = cfg['raspbee']['deconz']['port']
        self._token = cfg['raspbee']['deconz']['api_token']
        self._api_url = 'http://' + self._gateway + ':' + str(self._tcp_port) + '/api/' + self._token

        # Currently I don't want a generic approach but rather know 
        # exactly (hardcoded) which plugs I control programatically
        
        ######## Plugs to actually control the heating
        # Map deconz plug name to human-readable display name
        self._heating_plug_display_name_mapping = {
            cfg['raspbee']['heating']['plug_names']['flat'] : cfg['raspbee']['heating']['display_names']['flat'],
            cfg['raspbee']['heating']['plug_names']['basement'] : cfg['raspbee']['heating']['display_names']['basement']
        }

        # Map deconz plug name to deconz ID
        self._heating_plug_raspbee_name_mapping = self._map_deconz_heating_plugs(cfg)

        ######## Temperature sensors
        # Map deconz sensor name to human-readable display name
        self._temperature_sensor_display_name_mapping = {
            cfg['raspbee']['temperature']['sensor_names']['living_room'] : cfg['raspbee']['temperature']['display_names']['living_room']
        }

        # Map deconz sensor name to deconz ID
        self._temperature_sensor_raspbee_name_mapping = self._map_deconz_temperature_sensors(cfg)

        # Load ordering of temperature sensors to query for heating-reference-temperature (heating
        # will be stopped, once this sensor reports the configured temperature)
        self._heating_preferred_reference_temperature_sensor_order = cfg['raspbee']['temperature']['preferred_heating_reference']


    @property
    def api_url(self):
        return self._api_url


    def lookup_heating_display_name(self, raspbee_id):
        for lbl, rid in self._heating_plug_raspbee_name_mapping.items():
            if rid == raspbee_id:
                return self._heating_plug_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    
    def lookup_temperature_display_name(self, raspbee_id):
        for lbl, rids in self._temperature_sensor_raspbee_name_mapping.items():
            if raspbee_id in rids:
                return self._temperature_sensor_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)



    def _map_deconz_heating_plugs(self, cfg):
        # Our 'smart' plugs are linked to the zigbee gateway as "lights"
        r = hu.http_get_request(self.api_url + '/lights')
        if r is None:
            return dict()

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
                    self._heating_plug_display_name_mapping[light['name']], raspbee_id))
                mapping[light['name']] = raspbee_id
        return mapping


    def _map_deconz_temperature_sensors(self, cfg):
        # Each of our sensors is takes up 3 separate raspbee IDs (temperature, humidity, pressure)
        r = hu.http_get_request(self.api_url + '/sensors')
        if r is None:
            return dict()

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
                    self._temperature_sensor_display_name_mapping[s], raspbee_id))
                if s in mapping:
                    mapping[s].append(raspbee_id)
                else:
                    mapping[s] = [raspbee_id]
        return mapping


    @property
    def known_power_plug_ids(self):
        return list(self._heating_plug_raspbee_name_mapping.values())


    @property
    def known_temperature_sensor_ids(self):
        known_ids = list()
        for _, ids in self._temperature_sensor_raspbee_name_mapping.items():
            known_ids.extend(ids)
        return known_ids


    def query_full_state(self):
        r = hu.http_get_request(self.api_url)
        if r is None:
            return list()
        state = json.loads(r.content)
        # print(json.dumps(state, indent=2))

        msg = ['*Heizung:*']
        msg.append('\u2022 deCONZ API Version: {}'.format(hu.format_num('s', state['config']['apiversion'])))
        msg.append('\u2022 deCONZ SW Version: {}'.format(hu.format_num('s', state['config']['swversion'])))
        msg.append('\u2022 ZigBee Kanal: {}'.format(hu.format_num('d', state['config']['zigbeechannel'])))

        # Iterate over reported lights (this group contains our power plugs)
        is_heating = None
        for raspbee_id in state['lights']:
            if raspbee_id in self.known_power_plug_ids:
                plug = PlugState(self.lookup_heating_display_name(raspbee_id), state['lights'][raspbee_id])
                msg.append('\u2022 Steckdose für ' + plug.format_message(use_markdown=True, detailed_information=True))
                is_heating = (is_heating if is_heating is not None else False) or plug.on
        
        if is_heating is not None:
            msg.insert(1, '\u2022 Heizung ist {}'.format('ein :thermometer:' if is_heating else 'aus :snowman:'))
        else:
            msg.insert(1, '\u2022 :bangbang: Steckdosen sind nicht erreichbar!')


        sensors = list()
        for raspbee_id in state['sensors']:
            if raspbee_id in self.known_temperature_sensor_ids:
                sensors.append(TemperatureState(self.lookup_temperature_display_name(raspbee_id), state['sensors'][raspbee_id]))
        if len(sensors) == 0:
            msg.append('\u2022 :bangbang: Thermometer sind nicht erreichbar!')
        else:
            sensors = TemperatureState.merge_sensors(sensors)
            msg.append('\n*Thermometer:*')
            for sensor in sensors:
                msg.append('  \u2022 ' + sensor.format_message(use_markdown=True, detailed_information=True))

        return '\n'.join(msg)


    def query_heating(self):
        """:return: flag (True if currently heating), list of PlugState"""
        status = list()
        is_heating = False
        logger = logging.getLogger()
        if len(self._heating_plug_raspbee_name_mapping) == 0:
            logger.error('Cannot query heating, as there are no known/reachable plugs!')
            return None, list()

        for plug_lbl, plug_id in self._heating_plug_raspbee_name_mapping.items():
            r = hu.http_get_request(self.api_url + '/lights/' + plug_id)
            if r is None:
                return None, status # Abort query
            state = PlugState(self._heating_plug_display_name_mapping[plug_lbl], json.loads(r.content))
            status.append(state)
            # logger.info(state)
            is_heating = is_heating or state.on
        return is_heating, status


    def query_temperature(self):
        status = list()
        logger = logging.getLogger()
        if len(self._temperature_sensor_raspbee_name_mapping) == 0:
            logger.error('Cannot query temperature, as there are no known/reachable sensors!')
            return None

        for sensor_lbl, sensor_ids in self._temperature_sensor_raspbee_name_mapping.items():
            merged_state = None
            for sensor_id in sensor_ids:
                r = hu.http_get_request(self.api_url + '/sensors/' + sensor_id)
                if r is None:
                    return None # Abort query
                state = TemperatureState(self._temperature_sensor_display_name_mapping[sensor_lbl], json.loads(r.content))
                if merged_state is None:
                    merged_state = state
                else:
                    merged_state = merged_state.merge(state)
            status.append(merged_state)
        return status


    def query_temperature_for_heating(self):
        """To adjust the heating, we need a reference temperature reading.
        However, sensors may be unreachable. Thus, we can configure a 
        "preferred reference temperature sensor order" which we iterate
        to obtain a valid reading. If no sensor is available, return None.
        """
        temp_states = self.query_temperature()
        if temp_states is None:
            return None
        temp_dict = {t.name: t for t in temp_states}
        for sensor_name in self._heating_preferred_reference_temperature_sensor_order:
            if sensor_name in temp_dict:
                return temp_dict[sensor_name].temperature
        return None


    def switch_light(self, light_id, turn_on):
        r = hu.http_put_request(self.api_url + '/lights/' + light_id + '/state', 
            '{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        if r is None:
            return False, 'Exception während {:s}schalten von {:s}. Log überprüfen!'.format(
                    'Ein' if turn_on else 'Aus', self.lookup_heating_display_name(light_id)
                )

        # r = requests.put(self.api_url + '/lights/' + light_id + '/state', 
        #     data='{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        if r.status_code != 200:
            return False, 'Fehler (HTTP {:d}) beim {:s}schalten von {:s}.'.format(
                r.status_code, 'Ein' if turn_on else 'Aus', self.lookup_heating_display_name(light_id))
        else:
            return True, '{:s} wurde {:s}geschaltet.'.format(self.lookup_heating_display_name(light_id), 
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
        msg = list()
        for _, plug_id in self._heating_plug_raspbee_name_mapping.items():
            s, m = self.switch_light(plug_id, True)
            success = success and s
            msg.append(m)
        return success, '\n'.join(msg)


    def turn_off(self):
        is_heating, _ = self.query_heating()
        if not is_heating:
            return True, 'Heizung ist schon aus.'
        # Since this is an or-relais, we need to turn off all heating plugs
        success = True
        msg = list()
        for _, plug_id in self._heating_plug_raspbee_name_mapping.items():
            s, m = self.switch_light(plug_id, False)
            success = success and s
            msg.append(m)
        return success, '\n'.join(msg)


class DummyRaspBeeWrapper:
    #Used to develop without actually switching the heater on/off
    def __init__(self, cfg):
        # Deconz parameters
        self._gateway = cfg['raspbee']['deconz']['gateway']
        self._tcp_port = cfg['raspbee']['deconz']['port']
        self._token = cfg['raspbee']['deconz']['api_token']
        self._api_url = 'http://' + self._gateway + ':' + str(self._tcp_port) + '/api/' + self._token

        # Currently I don't want a generic approach but rather know 
        # exactly (hardcoded) which plugs I control programatically
        
        ######## Plugs to actually control the heating
        # Map deconz plug name to human-readable display name
        self._heating_plug_display_name_mapping = {
            cfg['raspbee']['heating']['plug_names']['flat'] : cfg['raspbee']['heating']['display_names']['flat'],
            cfg['raspbee']['heating']['plug_names']['basement'] : cfg['raspbee']['heating']['display_names']['basement']
        }

        # Map deconz plug name to deconz ID
        self._heating_plug_raspbee_name_mapping = self._map_deconz_heating_plugs(cfg)

        ######## Temperature sensors
        # Map deconz sensor name to human-readable display name
        self._temperature_sensor_display_name_mapping = {
            cfg['raspbee']['temperature']['sensor_names']['living_room'] : cfg['raspbee']['temperature']['display_names']['living_room']
        }

        # Map deconz sensor name to deconz ID
        self._temperature_sensor_raspbee_name_mapping = self._map_deconz_temperature_sensors(cfg)

        # Load ordering of temperature sensors to query for heating-reference-temperature (heating
        # will be stopped, once this sensor reports the configured temperature)
        self._heating_preferred_reference_temperature_sensor_order = cfg['raspbee']['temperature']['preferred_heating_reference']

        self.is_dummy_heating = False


    @property
    def api_url(self):
        return self._api_url


    def lookup_heating_display_name(self, raspbee_id):
        for lbl, rid in self._heating_plug_raspbee_name_mapping.items():
            if rid == raspbee_id:
                return self._heating_plug_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    
    def lookup_temperature_display_name(self, raspbee_id):
        for lbl, rids in self._temperature_sensor_raspbee_name_mapping.items():
            if raspbee_id in rids:
                return self._temperature_sensor_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)


    def _map_deconz_heating_plugs(self, cfg):
        # Our 'smart' plugs are linked to the zigbee gateway as "lights"
        r = hu.http_get_request(self.api_url + '/lights')
        if r is None:
            return dict()

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
                    self._heating_plug_display_name_mapping[light['name']], raspbee_id))
                mapping[light['name']] = raspbee_id
        return mapping


    def _map_deconz_temperature_sensors(self, cfg):
        # Each of our sensors is takes up 3 separate raspbee IDs (temperature, humidity, pressure)
        r = hu.http_get_request(self.api_url + '/sensors')
        if r is None:
            return dict()

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
                    self._temperature_sensor_display_name_mapping[s], raspbee_id))
                if s in mapping:
                    mapping[s].append(raspbee_id)
                else:
                    mapping[s] = [raspbee_id]
        return mapping


    @property
    def known_power_plug_ids(self):
        return list(self._heating_plug_raspbee_name_mapping.values())


    @property
    def known_temperature_sensor_ids(self):
        known_ids = list()
        for _, ids in self._temperature_sensor_raspbee_name_mapping.items():
            known_ids.extend(ids)
        return known_ids


    def query_full_state(self):
        r = hu.http_get_request(self.api_url)
        if r is None:
            return list()
        state = json.loads(r.content)
        # print(json.dumps(state, indent=2))

        msg = ['*Heizung:*']
        msg.append('\u2022 deCONZ API Version: {}'.format(hu.format_num('s', state['config']['apiversion'])))
        msg.append('\u2022 deCONZ SW Version: {}'.format(hu.format_num('s', state['config']['swversion'])))
        msg.append('\u2022 ZigBee Kanal: {}'.format(hu.format_num('d', state['config']['zigbeechannel'])))

        # Iterate over reported lights (this group contains our power plugs)
        is_heating = None
        for raspbee_id in state['lights']:
            if raspbee_id in self.known_power_plug_ids:
                plug = PlugState(self.lookup_heating_display_name(raspbee_id), state['lights'][raspbee_id])
                msg.append('\u2022 Steckdose für ' + plug.format_message(use_markdown=True, detailed_information=True))
                is_heating = (is_heating if is_heating is not None else False) or plug.on
        
        if is_heating is not None:
            msg.insert(1, '\u2022 Heizung ist {}'.format('ein :sunny:' if is_heating else 'aus :snowman:'))
        else:
            msg.insert(1, '\u2022 :bangbang: Steckdosen sind nicht erreichbar!')


        sensors = list()
        for raspbee_id in state['sensors']:
            if raspbee_id in self.known_temperature_sensor_ids:
                sensors.append(TemperatureState(self.lookup_temperature_display_name(raspbee_id), state['sensors'][raspbee_id]))
        if len(sensors) == 0:
            msg.append('\u2022 :bangbang: Thermometer sind nicht erreichbar!')
        else:
            sensors = TemperatureState.merge_sensors(sensors)
            msg.append('\n*Thermometer:*')
            for sensor in sensors:
                msg.append('  \u2022 ' + sensor.format_message(use_markdown=True, detailed_information=True))

        return '\n'.join(msg)


    def query_heating(self):
        """:return: flag (True if heating currently heating), list of PlugState"""
        return self.is_dummy_heating, list()


    def query_temperature(self):
        status = list()
        logger = logging.getLogger()
        if len(self._temperature_sensor_raspbee_name_mapping) == 0:
            logger.error('Cannot query temperature, as there are no known/reachable sensors!')
            return None

        for sensor_lbl, sensor_ids in self._temperature_sensor_raspbee_name_mapping.items():
            merged_state = None
            for sensor_id in sensor_ids:
                r = hu.http_get_request(self.api_url + '/sensors/' + sensor_id)
                if r is None:
                    return None # Abort query
                state = TemperatureState(self._temperature_sensor_display_name_mapping[sensor_lbl], json.loads(r.content))
                if merged_state is None:
                    merged_state = state
                else:
                    merged_state = merged_state.merge(state)
            status.append(merged_state)
        return status


    def query_temperature_for_heating(self):
        """To adjust the heating, we need a reference temperature reading.
        However, sensors may be unreachable. Thus, we can configure a 
        "preferred reference temperature sensor order" which we iterate
        to obtain a valid reading. If no sensor is available, return None.
        """
        temp_states = self.query_temperature()
        if temp_states is None:
            return None
        temp_dict = {t.name: t for t in temp_states}
        for sensor_name in self._heating_preferred_reference_temperature_sensor_order:
            if sensor_name in temp_dict:
                return temp_dict[sensor_name].temperature
        return None


    def switch_light(self, light_id, turn_on):
        self.is_dummy_heating = turn_on
        return True, 'Dummy'
        # r = hu.http_put_request(self.api_url + '/lights/' + light_id + '/state', 
        #     '{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        # if r is None:
        #     return False, 'Exception während {:s}schalten von {:s}. Log überprüfen!'.format(
        #             'Ein' if turn_on else 'Aus', self.lookup_heating_display_name(light_id)
        #         )

        # # r = requests.put(self.api_url + '/lights/' + light_id + '/state', 
        # #     data='{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        # if r.status_code != 200:
        #     return False, 'Fehler (HTTP {:d}) beim {:s}schalten von {:s}.'.format(
        #         r.status_code, 'Ein' if turn_on else 'Aus', self.lookup_heating_display_name(light_id))
        # else:
        #     return True, '{:s} wurde {:s}geschaltet.'.format(self.lookup_heating_display_name(light_id), 
        #         'ein' if turn_on else 'aus')
            

    def turn_on(self):
        is_heating, _ = self.query_heating()
        if is_heating:
            return True, 'Heizung läuft schon.'
        # Technically (or-relais), we only need to turn on one.
        # But to have a less confusing status report, turn all on:
        # _, plug_id = next(iter(self.heater_plug_mapping.items()))
        # self.switch_light(plug_id, True)
        success = True
        msg = list()
        for _, plug_id in self._heating_plug_raspbee_name_mapping.items():
            s, m = self.switch_light(plug_id, True)
            success = success and s
            msg.append(m)
        return success, '\n'.join(msg)


    def turn_off(self):
        is_heating, _ = self.query_heating()
        if not is_heating:
            return True, 'Heizung ist schon aus.'
        # Since this is an or-relais, we need to turn off all heating plugs
        success = True
        msg = list()
        for _, plug_id in self._heating_plug_raspbee_name_mapping.items():
            s, m = self.switch_light(plug_id, False)
            success = success and s
            msg.append(m)
        return success, '\n'.join(msg)
