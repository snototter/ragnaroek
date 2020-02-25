#!/usr/bin/python
# coding=utf-8
"""E-Paper wrapper for Waveshare modules."""

import logging
import traceback

try:
    from .waveshare.epd4in2 import EPD
    _use_display = True
except RuntimeError:
    _use_display = False
    class EPD(object):
        def __init__(self):
            logging.getLogger().warning("[EPD] You're using the dummy EPD implementation, because waveshare couldn't be loaded!")
        
        def init(self):
            pass

        def Clear(self):
            pass

        def getbuffer(self, img):
            return None

        def display(self, img):
            return None
    
# from . import broadcasting

class EPaperDisplay(object):
    def __init__(self, cfg):
        print(cfg['display']['refresh_time']) #TODO
        self._epd = EPD()
        self._epd.init()
        self._epd.Clear()
        logging.getLogger().info('[EPaperDisplay] Initialized display wrapper')
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

    def show_test_image(self):
        from PIL import Image
        img = Image.open('test.bmp')
        self._epd.display(epd.getbuffer(img))
