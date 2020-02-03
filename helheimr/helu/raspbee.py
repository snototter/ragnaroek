#!/usr/bin/python
# coding=utf-8
"""Wrapper to access the RaspBee gateway.
**Note:** as of 10/2019 we don't use the ZigBee plugs anymore,
because the Osram plugs disconnect too frequently.

Initially, this was meant to control the power switch - but zigbee
is very(!) sensitive to nearby WIFIs. So it became pretty much
useless (deCONZ couldn't reach the plug 10/24h each day).
The thermometers, however, worked fine all the time.

So this is a hybrid solution: use zigbee to query temperature,
but rely on LPD433 which reliably switches the (much cheaper)
plugs. The only downside is, that we don't know the current
state of the plug.
"""

import json
import logging

from . import common
from . import network_utils


class PlugState:
    """State of a 'smart' ZigBee plug."""
    def __init__(self, display_name, deconz_plug):
        self.display_name = display_name                    # Readable name
        self.name = deconz_plug['name']                     # Name/label within the deconz/phoscon gateway
        self.reachable = deconz_plug['state']['reachable']  # Flag indicating the plug's connection status
        self.on = deconz_plug['state']['on']                # Currently on or off?

    def __str__(self):
        return "{:s} ist {:s}erreichbar und {:s}".format(
            self.display_name,
            '' if self.reachable else '*nicht* ',
            'ein' if self.on else 'aus')

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
    """State of a 'smart' temperature/humidity/pressure sensor."""
    def __init__(self, display_name, deconz_sensor):
        self.display_name = display_name     # Readable name
        self.name = deconz_sensor['name']    # Name/label within the deconz/phoscon gateway
        self.humidity = None
        self.pressure = None
        self.temperature = None
        self.battery_level = deconz_sensor['config']['battery']
        self.reachable = deconz_sensor['config']['reachable']

        state = deconz_sensor['state']
        if deconz_sensor['type'] == 'ZHATemperature':
            self.temperature = state['temperature'] / 100.0
        elif deconz_sensor['type'] == 'ZHAHumidity':
            self.humidity = state['humidity'] / 100.0
        elif deconz_sensor['type'] == 'ZHAPressure':
            self.pressure = state['pressure']

    def __str__(self):
        return '{:s}: {:.1f}°C bei {:.1f}% Luftfeuchte und {:d}hPa Luftdruck, Batteriestatus: {:d}%'.format(
            self.display_name,
            -999 if self.temperature is None else self.temperature,
            -999 if self.humidity is None else self.humidity,
            -9999 if self.pressure is None else self.pressure,
            -9999 if self.battery_level is None else self.battery_level)

    def merge(self, other):
        """deconz reports three separate sensors for the same physical device, so we need
        to merge these states into one again..."""
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

        if self.reachable is None:
            self.reachable = other.reachable
        elif other.reachable is not None:
            self.reachable = self.reachable and other.reachable
        return self

    def format_message(self, use_markdown=True, detailed_information=False):
        # hair space: U+200A, thin space: U+2009
        #         common.format_num('d', self.pressure, use_markdown))
        txt = '{}{}{}: {}\u200a°, {}\u200a%'.format(
                '_' if use_markdown else '',
                self.display_name,
                '_' if use_markdown else '',
                common.format_num('.1f', self.temperature, use_markdown),
                common.format_num('d', int(self.humidity), use_markdown))

        if detailed_information or (self.battery_level is not None and self.battery_level < 20):
            txt += ', {}\u200a% Akku{:s}'.format(
                '?' if self.battery_level is None else common.format_num('d', int(self.battery_level),
                    use_markdown),
                ' :warning:' if use_markdown and (self.battery_level is not None and self.battery_level < 20) else '')

        if not self.reachable:
            txt += ' {}nicht erreichbar!{}'.format(':bangbang: *' if use_markdown else '', '*' if use_markdown else '')
        return txt

    @staticmethod
    def merge_sensors(sensor_list):
        """deconz reports three separate sensors for the same physical device, so we need
        to merge these states into one again..."""
        if len(sensor_list) == 0:
            return list()
        sorted_sensors = sorted(sensor_list, key=lambda s: s.name)
        merged = [sorted_sensors[0]]
        for i in range(1, len(sorted_sensors)):
            if sorted_sensors[i].name != merged[-1].name:
                merged.append(sorted_sensors[i])
            else:
                merged[-1] = merged[-1].merge(sorted_sensors[i])
        return merged


def get_api_url(cfg):
    gateway = cfg['raspbee']['deconz']['gateway']
    tcp_port = cfg['raspbee']['deconz']['port']
    token = cfg['raspbee']['deconz']['api_token']
    return 'http://' + gateway + ':' + str(tcp_port) + '/api/' + token


class RaspBeeWrapper:
    """ Communication with the zigbee/raspbee (deconz REST API) gateway """
    def __init__(self, cfg):
        self._api_url = get_api_url(cfg)

        # Map deconz plug name to human-readable display name
        if 'heating' in cfg['raspbee']:
            self._heating_plug_display_name_mapping = {
                cfg['raspbee']['heating']['plug_names'][k]: cfg['raspbee']['heating']['display_names'][k]
                    for k in cfg['raspbee']['heating']['plug_names']
            }
            # Map deconz plug name to deconz ID
            self._heating_plug_raspbee_name_mapping = self.__map_deconz_heating_plugs(cfg)
            self._heating_disabled = False
        else:
            logging.getLogger().warning('[RaspbeeWrapper] No ZigBee heating plugs configured!')
            self._heating_disabled = True

        # ####### Temperature sensors
        # Map deconz sensor name to human-readable display name
        self._temperature_sensor_display_name_mapping = {
            cfg['raspbee']['temperature']['sensor_names'][k]: cfg['raspbee']['temperature']['display_names'][k]
                for k in cfg['raspbee']['temperature']['display_names']
        }

        # Map deconz sensor name to deconz ID
        self._temperature_sensor_raspbee_name_mapping = self.__map_deconz_temperature_sensors(cfg)

        # Load ordering of temperature sensors to query for heating-reference-temperature (heating
        # will be stopped, once this sensor reports the configured temperature)
        self._heating_preferred_reference_temperature_sensor_order = \
            cfg['raspbee']['temperature']['preferred_heating_reference']

    @property
    def api_url(self):
        return self._api_url

    def __lookup_heating_display_name(self, raspbee_id):
        for lbl, rid in self._heating_plug_raspbee_name_mapping.items():
            if rid == raspbee_id:
                return self._heating_plug_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    def __lookup_temperature_display_name(self, raspbee_id):
        for lbl, rids in self._temperature_sensor_raspbee_name_mapping.items():
            if raspbee_id in rids:
                return self._temperature_sensor_display_name_mapping[lbl]
        return 'ID {}'.format(raspbee_id)

    def __map_deconz_heating_plugs(self, cfg):
        # Our 'smart' plugs are linked to the zigbee gateway as "lights"
        r = network_utils.http_get_request(self.api_url + '/lights')
        if r is None:
            return dict()

        lights = json.loads(r.content)
        logger = logging.getLogger()

        plug_names = [cfg['raspbee']['heating']['plug_names'][k] for k in cfg['raspbee']['heating']['plug_names']]
        mapping = dict()

        for raspbee_id, light in lights.items():
            if light['name'] in plug_names:
                logger.info(
                    '[RaspBeeWrapper] Mapping plug {:s} ({:s}) to RaspBee ID {}'.format(light['name'],
                    self._heating_plug_display_name_mapping[light['name']], raspbee_id))
                mapping[light['name']] = raspbee_id
        return mapping

    def __map_deconz_temperature_sensors(self, cfg):
        # Each of our sensors takes up 3 separate raspbee IDs (temperature, humidity, pressure)
        r = network_utils.http_get_request(self.api_url + '/sensors')
        if r is None:
            return dict()

        sensors = json.loads(r.content)
        logger = logging.getLogger()

        sensor_names = [
            cfg['raspbee']['temperature']['sensor_names'][k]
            for k in cfg['raspbee']['temperature']['sensor_names']]
        mapping = dict()

        for raspbee_id, sensor in sensors.items():
            s = sensor['name']
            if s in sensor_names:
                logger.info(
                    '[RaspBeeWrapper] Mapping sensor {:s} ({:s}) to RaspBee ID {}'.format(s,
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

    def query_deconz_details(self):
        r = network_utils.http_get_request(self.api_url)
        if r is None:
            return list()
        state = json.loads(r.content)
        # print(json.dumps(state, indent=2))

        msg = ['*ZigBee/RaspBee:*']
        msg.append('\u2022 deCONZ API Version: {}'.format(common.format_num('s', state['config']['apiversion'])))
        msg.append('\u2022 deCONZ SW Version: {}'.format(common.format_num('s', state['config']['swversion'])))
        msg.append('\u2022 ZigBee Kanal: {}'.format(common.format_num('d', state['config']['zigbeechannel'])))
        # # Note: LPD433 replaced the ZigBee plugs, so we don't need to query those:
        # # Iterate over reported lights (this group contains our power plugs)
        # is_heating = None
        # for raspbee_id in state['lights']:
        #     if raspbee_id in self.known_power_plug_ids:
        #         plug = PlugState(self.__lookup_heating_display_name(raspbee_id), state['lights'][raspbee_id])
        #         msg.append('\u2022 Steckdose für ' + plug.format_message(use_markdown=True, detailed_information=True))
        #         is_heating = (is_heating if is_heating is not None else False) or plug.on
        # if is_heating is not None:
        #     msg.insert(1, '\u2022 Heizung ist {}'.format('ein :thermometer:' if is_heating else 'aus :snowman:'))
        # else:
        #     msg.insert(1, '\u2022 :bangbang: Steckdosen sind nicht erreichbar!')

        # sensors = list()
        # for raspbee_id in state['sensors']:
        #     if raspbee_id in self.known_temperature_sensor_ids:
        #         sensors.append(TemperatureState(self.__lookup_temperature_display_name(raspbee_id), state['sensors'][raspbee_id]))
        # if len(sensors) == 0:
        #     msg.append('\u2022 :bangbang: Thermometer sind nicht erreichbar!')
        # else:
        #     sensors = TemperatureState.merge_sensors(sensors)
        #     msg.append('\n*Thermometer:*')
        #     for sensor in sensors:
        #         msg.append('  \u2022 ' + sensor.format_message(use_markdown=True, detailed_information=True))
        return '\n'.join(msg)

    def query_heating(self):
        """:return: flag (True if currently heating), list of PlugState"""
        if self._heating_disabled:
            logging.getLogger().error(
                '[RaspBeeWrapper] ZigBee plugs have been replaced by LPD433, so you should not call query_heating()!')
            return None, list()

        status = list()
        is_heating = False
        logger = logging.getLogger()
        if len(self._heating_plug_raspbee_name_mapping) == 0:
            logger.error('[RaspBeeWrapper] Cannot query heating, as there are no known/reachable plugs!')
            return None, list()
        for plug_lbl, plug_id in self._heating_plug_raspbee_name_mapping.items():
            r = network_utils.http_get_request(self.api_url + '/lights/' + plug_id)
            if r is None:
                return None, status  # Abort query
            state = PlugState(self._heating_plug_display_name_mapping[plug_lbl], json.loads(r.content))
            status.append(state)
            is_heating = is_heating or state.on
        return is_heating, status

    def query_temperature(self):
        status = list()
        logger = logging.getLogger()
        if len(self._temperature_sensor_raspbee_name_mapping) == 0:
            logger.error('[RaspBeeWrapper] Cannot query temperature, as there are no known/reachable sensors!')
            return None

        for sensor_lbl, sensor_ids in self._temperature_sensor_raspbee_name_mapping.items():
            merged_state = None
            for sensor_id in sensor_ids:
                r = network_utils.http_get_request(self.api_url + '/sensors/' + sensor_id)
                if r is None:
                    return None  # Abort query
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
            if sensor_name in temp_dict and temp_dict[sensor_name].reachable:
                return temp_dict[sensor_name].temperature
        logging.getLogger().error('[RaspBeeWrapper] No preferred sensor is reachable!')
        return None

    def __switch_light(self, light_id, turn_on):
        r = network_utils.http_put_request(
            self.api_url + '/lights/' + light_id + '/state',
            '{:s}'.format('{"on":true}' if turn_on else '{"on":false}'))
        if r is None:
            return False, 'Exception während {:s}schalten von {:s}. Log überprüfen!'.format(
                    'Ein' if turn_on else 'Aus', self.__lookup_heating_display_name(light_id)
                )

        if r.status_code != 200:
            return False, 'Fehler (HTTP {:d}) beim {:s}schalten von {:s}.'.format(
                r.status_code, 'Ein' if turn_on else 'Aus', self.__lookup_heating_display_name(light_id))
        else:
            return True, '{:s} wurde {:s}geschaltet.'.format(
                self.__lookup_heating_display_name(light_id),
                'ein' if turn_on else 'aus')

    def turn_on(self):
        if self._heating_disabled:
            return False, 'ZigBee Stecker wurden durch LPD433 ersetzt.'

        is_heating, _ = self.query_heating()
        if is_heating:
            return True, 'Heizung läuft schon.'
        # Technically (or-relais), we only need to turn on one.
        # But to have a less confusing status report, turn all on:
        # _, plug_id = next(iter(self.heater_plug_mapping.items()))
        # self.__switch_light(plug_id, True)
        success = True
        msg = list()
        for _, plug_id in self._heating_plug_raspbee_name_mapping.items():
            s, m = self.__switch_light(plug_id, True)
            success = success and s
            msg.append(m)
        return success, '\n'.join(msg)

    def turn_off(self):
        if self._heating_disabled:
            return False, 'ZigBee Stecker wurden durch LPD433 ersetzt.'

        is_heating, _ = self.query_heating()
        if not is_heating:
            return True, 'Heizung ist schon aus.'
        # Since this is an or-relais, we need to turn off all heating plugs
        success = True
        msg = list()
        for _, plug_id in self._heating_plug_raspbee_name_mapping.items():
            s, m = self.__switch_light(plug_id, False)
            success = success and s
            msg.append(m)
        return success, '\n'.join(msg)
