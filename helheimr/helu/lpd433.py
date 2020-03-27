#!/usr/bin/python
# coding=utf-8
"""Basic 433MHz transmit functionality.

I found out about rpi-rf from this basic tutorial:
https://www.instructables.com/id/RF-433-MHZ-Raspberry-Pi/

Uses https://pypi.org/project/rpi-rf/ to transmit LPD433 codes.

If you need to find out your device's codes, protocols, etc. use
https://github.com/ninjablocks/433Utils

I followed this tutorial:
  https://tutorials-raspberrypi.de/raspberry-pi-funksteckdosen-433-mhz-steuern/
Basically, all you need to do is `make && sudo ./RFSniffer`
If you have a cheap receiver, make sure to hold the remote/device
as close as possible to the rx (mine lost connection as soon as I was
5 cm (!) away from the receiver).

Worked out-of-the-box (once you figure out the GPIO pin numbering)
and has less configuration overhead (and almost no installation
headache) compared to pilight (search for pilight installation on
latest raspbian to get a glimpse of the (currently) necessary
workarounds needed ;-)
"""

import logging
import traceback

from . import broadcasting

try:
    # Can only be run on Raspberry Pi ;-)
    from rpi_rf import RFDevice
except RuntimeError:
    logging.getLogger().error('[LPD433] Can only be run on Raspberry Pi - declaring a dummy RFDevice for debugging now.')

    class RFDevice(object):
        """Dummy RFDevice class for debugging on non-raspberrypi platforms."""
        def __init__(self, gpio):
            self.tx_repeat = None

        def enable_tx(self):
            pass

        def tx_code(self, code, protocol, pulse_length, code_length):
            logging.getLogger().warning('[LPD433] Dummy RFDevice cannot send code via tx_code()')

        def cleanup(self):
            pass


class LpdDeviceState(object):
    def __init__(self, display_name, powered_on):
        self._display_name = display_name
        self._powered_on = powered_on

    def __str__(self):
        return '{:s} is {:s}'.format(self._display_name, 'on' if self._powered_on else 'off')

    def to_status_line(self):
        return '{:s} ist {:s}'.format(self._display_name, 'ein' if self._powered_on else 'aus')


class LpdDevice(object):
    """Abstraction of an LPD433 device (i.e. a power plug).
    Use this to turn the device on/off.
    """
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
            logging.getLogger().debug("[LPD433] Sending '{} ({:s})' to '{}'".format(code,
                'on' if code == self._code_on else 'off',
                self._display_name))
            rfdevice = RFDevice(self._gpio_pin)
            rfdevice.enable_tx()
            rfdevice.tx_repeat = self._send_repeat
            rfdevice.tx_code(code, self._protocol, self._pulse_length, self._code_length)
            rfdevice.cleanup()
            return True
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error("[LPD433] Error while sending: " + err_msg)
            broadcasting.MessageBroadcaster.instance().error('Fehler beim {}schalten der Steckdosen:\n'.format(
                'Ein' if code == self._code_on else 'Aus') + err_msg)
            return False


class Lpd433Wrapper(object):
    def __init__(self, cfg):
        # GPIO pin number to send the radio data.
        self._tx_gpio_pin = cfg['lpd433']['gpio_pin_tx']

        # Configuration of the plugs used to turn the heating on/off.
        self._heating_plugs = [
            LpdDevice(self._tx_gpio_pin, cfg['lpd433']['heating']['plugs'][k])
            for k in cfg['lpd433']['heating']['plugs']]

        # Establish a "known" state (we'll never know for sure, but
        # from our experiments, FS1000A + antenna and 10 repeats will
        # switch any LPD433 in our flat, no matter what's in between tx/rx ;-)
        self.turn_off()
        for h in self._heating_plugs:
            logging.getLogger().info('[LPD433] Initialized plug: {}'.format(h))

    def turn_on(self):
        """Send 'on' command to all plugs configured as 'heating'."""
        success = [d.turn_on() for d in self._heating_plugs]
        return all(success)

    def turn_off(self):
        """Send 'off' command to all plugs configured as 'heating'."""
        success = [d.turn_off() for d in self._heating_plugs]
        return all(success)

    def query_heating(self):
        """Query state of the devices - since LPD433 doesn't transmit anything,
        we have to rely on software state monitoring (i.e. upon start up, all
        plugs are switched off and afterwards, we remember the sent commands).
        So use the result with a grain of salt."""
        is_on = [d.powered_on for d in self._heating_plugs]
        is_heating = any(is_on)

        states = [d.state for d in self._heating_plugs]
        return is_heating, states
