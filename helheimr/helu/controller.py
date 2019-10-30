#!/usr/bin/python
# coding=utf-8
"""Bang bang controller implementation (as our heating is either on or off)."""

import logging

#######################################################################
## Basic controlling stuff

class OnOffController:
    """Bang bang controller with hysteresis."""
    def __init__(self):
        self._desired_value = None
        self._hysteresis_threshold = None
        self._prev_response = None

    
    def set_desired_value(self, desired_value):
        self._desired_value = desired_value


    def set_hysteresis(self, threshold):
        self._hysteresis_threshold = threshold


    def update(self, actual_value):
        """Returns True/False indicating whether to turn the heater on or off."""
        if self._desired_value is None:
            logging.getLogger().error('OnOffController.update() called without setting a desired value first!')
            return False

        minv = self._desired_value if self._hysteresis_threshold is None else self._desired_value - self._hysteresis_threshold
        maxv = self._desired_value if self._hysteresis_threshold is None else self._desired_value + self._hysteresis_threshold

        response = False
        if actual_value < minv:
            response = True
        elif actual_value > maxv:
            response = False
        else:
            # Inside upper/lower threshold, keep doing what you did  
            if self._prev_response is None:
                response = False
            else:
                response = self._prev_response
        self._prev_response = response
        return response