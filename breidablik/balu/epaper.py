#!/usr/bin/python
# coding=utf-8
"""E-Paper wrapper for Waveshare modules."""

import logging
import traceback

# from . import broadcasting

class EPaperDisplay(object):
    def __init__(self, cfg):
        #TODO
        logging.getLogger().info('[EPaperDisplay] Initialized')
        # # GPIO pin number to send the radio data.
        # self._tx_gpio_pin = cfg['lpd433']['gpio_pin_tx']

        # # Configuration of the plugs used to turn the heating on/off.
        # self._heating_plugs = [
        #     LpdDevice(self._tx_gpio_pin, cfg['lpd433']['heating']['plugs'][k])
        #     for k in cfg['lpd433']['heating']['plugs']]

        # # Establish a "known" state (we'll never know for sure, but
        # # from our experiments, FS1000A + antenna and 10 repeats will
        # # switch any LPD433 in our flat, no matter what's in between tx/rx ;-)
        # self.turn_off()
        # for h in self._heating_plugs:
        #     logging.getLogger().info('[LPD433] Initialized plug: {}'.format(h))
