#!/usr/bin/python
# coding=utf-8

import logging

#######################################################################
## Basic controlling stuff

class OnOffController:
    """Bang bang controller with hysteresis."""
    def __init__(self):
        self.desired_value = None
        self.hysteresis_threshold = None
        self.prev_response = None

    
    def set_desired_value(self, desired_value):
        self.desired_value = desired_value


    def set_hysteresis(self, threshold):
        self.hysteresis_threshold = threshold


    def update(self, actual_value):
        if self.desired_value is None:
            logging.getLogger().error('OnOffController.update() called without setting a desired value first!')
            return False

        minv = self.desired_value if self.hysteresis_threshold is None else self.desired_value - self.hysteresis_threshold
        maxv = self.desired_value if self.hysteresis_threshold is None else self.desired_value + self.hysteresis_threshold

        response = False
        if actual_value < minv:
            response = True
        elif actual_value > maxv:
            response = False
        else:
            # Inside upper/lower threshold, keep doing what you did  
            if self.prev_response is None:
                response = False
            else:
                response = self.prev_response
        self.prev_response = response
        return response