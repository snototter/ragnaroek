#!/usr/bin/python
# coding=utf-8
"""Basic 433MHz transmit functionality."""

import logging
try:
    from rpi_rf import RFDevice
except RuntimeError:
    logging.getLogger().error('[LPD433] Can only be run on Raspberry Pi - declaring a dummy RFDevice for debugging now.')
    # Can only be run on Raspberry Pi ;-) 
    class RFDevice:
        def __init__(self, gpio):
            self.tx_repeat = None
        def enable_tx(self):
            pass
        def tx_code(self, code, protocol, pulse_length, code_length):
            pass
        def cleanup(self):
            pass


class LpdDeviceState:
    def __init__(self, display_name, powered_on):
        self._display_name = display_name
        self._powered_on = powered_on

    def __str__(self):
        return '{:s} is {:s}'.format(self._display_name, 'on' if self._powered_on else 'off')

    def to_status_line(self):
        return '{:s} ist {:s}'.format(self._display_name, 'ein' if self._powered_on else 'aus')


class LpdDevice:
    def __init__(self, gpio_pin, cfg_entry):
        self._gpio_pin = gpio_pin
        self._display_name = cfg_entry['display_name']
        self._protocol = cfg_entry['protocol']
        self._send_repeat = cfg_entry['send_repeat']
        self._pulse_length = cfg_entry['pulse_length']
        self._code_length = cfg_entry['code_length']
        self._code_on = cfg_entry['code_on']
        self._code_off = cfg_entry['code_off']
        self._powered_on = False

    
    def __str__(self):
        return '{:s} is {:s}'.format(self._display_name, 'on' if self._powered_on else 'off')


    def to_status_line(self):
        return '{:s} ist {:s}'.format(self._display_name, 'ein' if self._powered_on else 'aus')


    @property
    def state(self):
        return LpdDeviceState(self._display_name, self._powered_on)


    @property
    def powered_on(self):
        return self._powered_on


    def turn_on(self):
        self._powered_on = self.__send_code(self._code_on)
        return self._powered_on
    

    def turn_off(self):
        success = self.__send_code(self._code_off)
        if success:
            self._powered_on = False
        return success
        

    def __send_code(self, code):
        try:
            logging.getLogger().info("[LPD433] Sending '{} ({:s})' to '{}'".format(code, 
                'on' if code == self._code_on else 'off',
                self._display_name))
            rfdevice = RFDevice(self._gpio_pin)
            rfdevice.enable_tx()
            rfdevice.tx_repeat = self._send_repeat
            rfdevice.tx_code(code, self._protocol, self._pulse_length, self._code_length)
            rfdevice.cleanup()
            return True
        except:
            #TODO broadcast error
            return False


class Lpd433Wrapper:
    def __init__(self, cfg):
        self._tx_gpio_pin = cfg['lpd433']['gpio_pin_tx']

        self._heating_plugs = [LpdDevice(self._tx_gpio_pin, cfg['lpd433']['heating']['plugs'][k]) for k in cfg['lpd433']['heating']['plugs']]
        self.turn_off()
        for h in self._heating_plugs:
            logging.getLogger().info('[LPD433] Configured plug: {}'.format(h))


    def turn_on(self):
        success = [d.turn_on() for d in self._heating_plugs]
        return all(success)


    def turn_off(self):
        success = [d.turn_off() for d in self._heating_plugs]
        return all(success)


    def query_heating(self):
        is_on = [d.powered_on for d in self._heating_plugs]
        is_heating = any(is_on)

        states = [d.state for d in self._heating_plugs]
        return is_heating, states
