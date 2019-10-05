#!/usr/bin/python
# coding=utf-8
"""Controls the heater (or a dummy heater for debug purposes)."""

import datetime
import logging
import threading

from . import common
from . import controller
from . import raspbee
from . import time_utils


"""Heating can be turned on via manual request or via a scheduled job."""
HeatingRequest = common.enum(MANUAL=1, SCHEDULED=2)

class Heating:
    __instance = None

    __MIN_TEMPERATURE = 5.0
    __MAX_TEMPERATURE = 30.0
    __MIN_HYSTERESIS = 0.1
    __MAX_HYSTERESIS = 10.0
    __MAX_HEATING_DURATION = datetime.timedelta(hours=12)


    @staticmethod
    def instance():
        """Returns the singleton."""
        return Heating.__instance


    @staticmethod
    def init_instance(config, broadcaster):
        """
        Initialize the singleton.

        :param config:      libconfig++ system configuration
        :param broadcaster: object to broadcast info/warning/error messages
        """
        if Heating.__instance is None:
            Heating(config, broadcaster)
        return Heating.__instance


    def __init__(self, config, broadcaster):
        """Virtually private constructor, use Heating.init_instance() instead."""
        if Heating.__instance is not None:
            raise RuntimeError("Heating is a singleton!")
        Heating.__instance = self

        #FIXME switch to real system
        self._heating_system = raspbee.DummyRaspBeeWrapper(config)
        # self._heating_system = raspbee.RaspBeeWrapper(config)

        self._controller = controller.OnOffController()

        self._broadcaster = broadcaster

        # Parameters defining what we have to do when heating:
        self._target_temperature = None     # User wants a specific temperature...
        self._temperature_hysteresis = 0.5  # +/- some hysteresis threshold
        self._heating_duration = None       # Stop heating after this duration
        self._is_manual_request = False     # Flag to indicate whether we have an active manual request
        self._is_heating = False            # Used to notify the __heating_loop() that there was a stop_heating() request

        # Members related to the heating loop thread
        self._num_consecutive_errors_before_broadcast = config['heating']['num_consecutive_errors_before_broadcast'] # Num of retrys before broadcasting a heating error
        self._max_idle_time = config['heating']['idle_time'] # Max. time to wait between __heating_loop() iterations
        self._is_terminating = False     # During shutdown, we want to prevent start_heating() calls
        self._start_heating = False      # Used to notify the __heating_loop() that there was a start_heating() request
        self._run_heating_loop = True    # Flag to keep the heating thread alive
        self._lock = threading.Lock()    # Thread will wait on the condition variable (so we can notify
        self._condition_var = threading.Condition(self._lock) # it on shutdown or other changes
        self._heating_loop_thread = threading.Thread(target=self.__heating_loop)
        self._heating_loop_thread.start()


    def start_heating(self, request_type, target_temperature=None,
            temperature_hysteresis=0.5, duration=None):
        """
        :param request_type: HeatingRequest (manual takes precedence over scheduled)
        :param target_temperature: None or temperature to heat to
        :param target_hysteresis: hysteresis threshold
        :param duration: None or 
        """
        # Sanity checks:
        if self._is_terminating:
            return

        if target_temperature is not None and \
            (target_temperature < Heating.__MIN_TEMPERATURE or target_temperature > Heating.__MAX_TEMPERATURE):
            raise ValueError("Target temperature must be within [{}, {}], you requested {}".format(
                Heating.__MIN_TEMPERATURE, Heating.__MAX_TEMPERATURE, target_temperature))

        if temperature_hysteresis < Heating.__MIN_HYSTERESIS or temperature_hysteresis > Heating.__MAX_HYSTERESIS:
            raise ValueError("Hysteresis must be within [{}, {}], you requested {}".format(
                Heating.__MIN_HYSTERESIS, Heating.__MAX_HYSTERESIS, temperature_hysteresis))

        if request_type == HeatingRequest.PERIODIC and duration is None:
            raise ValueError("A scheduled heating job must provide a valid duration!")

        if duration is not None and duration > Heating.__MAX_HEATING_DURATION:
            raise ValueError("Duration cannot be longer than {} hours!".format(Heating.__MAX_HEATING_DURATION))

        if duration is not None and not isinstance(duration, datetime.timedelta):
            raise TypeError("Duration must be of type datetime.timedelta")

        # Acquire the lock, store this heat request.
        self._condition_var.acquire()
        if self._is_manual_request and request_type == HeatingRequest.PERIODIC:
            logging.getLogger().info("Ignoring the periodic heating request, because there is a manual request currently active.")
        else:
            self._target_temperature = target_temperature
            self._temperature_hysteresis = temperature_hysteresis
            self._heating_duration = duration
            self._start_heating = True

        self._condition_var.notify()
        self._condition_var.release()


    def stop_heating(self):
        """Stops the heater (if currently active). Will be invoked by the user manually."""
        self._condition_var.acquire()
        self.__stop_heating()
        self._condition_var.notify()
        self._condition_var.release()


    def __stop_heating(self):
        """You must hold the lock before calling this method!"""
        self._is_manual_request = False
        self._is_heating = False
        self._heating_system.turn_off()


    def run_blocking(self):
        self._heating_loop_thread.join()


    def shutdown(self):
        """Shut down gracefully."""
        self._is_terminating = True
        self._condition_var.acquire()
        # Stop heating
        self.__stop_heating()
        # Terminate thread
        self._run_heating_loop = False
        self._condition_var.notify()
        self._condition_var.release()
        # Wait for thread
        self._heating_loop_thread.join()


    def __heating_loop(self):
        end_time = None        # If heating duration is set, this holds the end time
        use_controller = False # If temperature +/- hysteresis is set, we use the on/off controller
        should_heat = False
        current_temperature = None
        consecutive_errors = 0
        
        self._condition_var.acquire()
        while self._run_heating_loop:
            # Check if there was an incoming manual/periodic heating request while we slept:
            if self._start_heating:
                # Something's changed, let's check how we should heat
                self._is_heating = True
                self._start_heating = False

                if self._target_temperature is not None:
                    self._controller.set_desired_value(self._target_temperature)
                    self._controller.set_hysteresis(self._temperature_hysteresis)
                    use_controller = True
                    logging.getLogger().info("[Heating] Starting BangBang to reach {:.1f} +/- {:.1f}°".format(self._target_temperature, self._temperature_hysteresis))
                else:
                    use_controller = False
                    logging.getLogger().info("[Heating] Starting manually (i.e. always on)")

                if self._heating_duration is None:
                    end_time = None
                    logging.getLogger().info("[Heating] This heating request can only be stopped manually!")
                else:
                    end_time = time_utils.dt_offset(self._heating_duration)
                    logging.getLogger().info("[Heating] This heating request will end at {}".format(time_utils.format(end_time)))

            # If we're heating and there is no error, this plug state list will be 
            # populated within the following if-branch.
            plug_states = None 

            if self._is_heating:
                # Should we turn the heater on or off?
                if use_controller:
                    current_temperature = self._heating_system.query_temperature_for_heating()
                    if current_temperature is None:
                        self._broadcaster.error('Ich konnte kein Thermometer abfragen - versuche jetzt, die Heizung einzuschalten.')
                        should_heat = True
                    else:
                        should_heat = self._controller.update(current_temperature)
                else:
                    should_heat = True

                # Is heating duration over?
                if end_time is not None and time_utils.dt_now() >= end_time:
                    self._is_heating = False
                    should_heat = False
                    logging.getLogger().info("[Heating] End time of this heating request has passed, turning off the heater.")

                # Tell the zigbee gateway to turn the heater on/off:
                if should_heat:
                    ret, msg = self._heating_system.turn_on()
                else:
                    ret, msg = self._heating_system.turn_off()

                # Error checking
                if not ret:
                    logging.getLogger().error('RaspBee wrapper could not execute turn on/off command:\n' + msg)
                    self._broadcaster.error('Heizung konnte nicht {}geschaltet werden:\n'.format('ein' if should_heat else 'aus') + msg)
                else:
                    # Check if heating is actually on/off
                    is_heating, plug_states = self._heating_system.query_heating()
                    if is_heating is not None and is_heating != should_heat:
                        # Increase error count, but retry before broadcasting:
                        consecutive_errors += 1


            # Check if all plugs are reachable
            if plug_states is None:
                is_heating, plug_states = self._heating_system.query_heating()
            if len(plug_states) == 0 or any([not plug.reachable for plug in plug_states]):
                consecutive_errors += 1

            # Report error if the plug didn't respond until now
            if consecutive_errors >= self._num_consecutive_errors_before_broadcast:
                is_heating, _ = self._heating_system.query_heating()
                self._broadcaster.error("Heizung reagiert nicht, bitte kontrollieren!")
                # Mute error broadcast for the next few retrys
                consecutive_errors = 0
            
            self._condition_var.wait(self._max_idle_time)
        self._condition_var.release()

