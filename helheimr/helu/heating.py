#!/usr/bin/python
# coding=utf-8
"""Controls the heater (or a dummy heater for debug purposes)."""
#TODO e-ink: thrudvang, bilskirnir, fensal, gjallarbru (bruecke ueber gjoell), breidablik
import datetime
import logging
import threading

from . import broadcasting
from . import common
from . import controller
from . import lpd433
from . import raspbee
from . import time_utils
from . import telegram_bot
from . import temperature_log
from . import scheduling

"""Heating can be turned on via manual request or via a scheduled job."""
HeatingRequest = common.enum(MANUAL=1, SCHEDULED=2)

class Heating:
    __instance = None

    MIN_TEMPERATURE = 5.0
    MAX_TEMPERATURE = 30.0
    MIN_HYSTERESIS = 0.1
    MAX_HYSTERESIS = 5.0
    MAX_HEATING_DURATION = datetime.timedelta(hours=12)
    MIN_HEATING_DURATION = datetime.timedelta(minutes=15)


    @staticmethod
    def instance():
        """Returns the singleton."""
        return Heating.__instance


    @staticmethod
    def init_instance(config):
        """
        Initialize the singleton.

        :param config:      libconfig++ system configuration
        """
        if Heating.__instance is None:
            Heating(config)
        return Heating.__instance


    @staticmethod
    def sanity_check(request_type, target_temperature, temperature_hysteresis, duration):
        if target_temperature is not None and \
            (target_temperature < Heating.MIN_TEMPERATURE or target_temperature > Heating.MAX_TEMPERATURE):
            return False, "Temperatur muss zwischen {} und {} liegen, nicht {}.".format(
                common.format_num('.1f', Heating.MIN_TEMPERATURE), 
                common.format_num('.1f', Heating.MAX_TEMPERATURE),
                common.format_num('.1f', target_temperature))

        if temperature_hysteresis is not None and \
            (temperature_hysteresis < Heating.MIN_HYSTERESIS or temperature_hysteresis > Heating.MAX_HYSTERESIS):
            return False, "Hysterese muss zwischen {} und {} liegen, nicht {}.".format(
                common.format_num('.1f', Heating.MIN_HYSTERESIS), 
                common.format_num('.1f', Heating.MAX_HYSTERESIS), 
                common.format_num('.1f', temperature_hysteresis))

        if request_type == HeatingRequest.SCHEDULED and duration is None:
            return False, "Ein Heizungsprogramm muss eine Dauer definieren."

        if duration is not None and not isinstance(duration, datetime.timedelta):
            return False, "Falscher Datentyp für Dauer des Heizungsprogrammes."

        if duration is not None and duration > Heating.MAX_HEATING_DURATION:
            return False, "Heizdauer kann nicht länger als {} Stunden betragen.".format(
                int(Heating.MAX_HEATING_DURATION.total_seconds()/3600))

        if duration is not None and duration < Heating.MIN_HEATING_DURATION:
            return False, "Heizdauer kann nicht kürzer als {} Minuten betragen.".format(
                int(Heating.MIN_HEATING_DURATION.total_seconds()/60))

        return True, ''


    def __init__(self, config):
        """Virtually private constructor, use Heating.init_instance() instead."""
        if Heating.__instance is not None:
            raise RuntimeError("Heating is a singleton!")
        Heating.__instance = self

        self._zigbee_gateway = raspbee.RaspBeeWrapper(config)

        self._lpd433_gateway = lpd433.Lpd433Wrapper(config)

        self._controller = controller.OnOffController()

        self._broadcaster = broadcasting.MessageBroadcaster.instance()

        # Parameters defining what we have to do when heating:
        self._target_temperature = None     # User wants a specific temperature...
        self._temperature_hysteresis = 0.5  # +/- some hysteresis threshold
        self._heating_duration = None       # Stop heating after this duration
        self._is_manual_request = False     # Flag to indicate whether we have an active manual request
        self._is_heating = False            # Used to notify the __heating_loop() that there was a stop_heating() request
        self._is_paused = False             # While paused, scheduled heating tasks will be ignored

        # Members related to the heating loop thread
        self._latest_request_by = None            # Name of user who requested the most recent heating job
        self._num_consecutive_errors_before_broadcast = \
            config['heating']['num_consecutive_errors_before_broadcast'] # Num of retrys before broadcasting a heating error
        self._max_idle_time = \
            config['heating']['idle_time']        # Max. time to wait between __heating_loop() iterations
        self._is_terminating = False              # During shutdown, we want to prevent start_heating() calls
        self._start_heating = False               # Used to notify the __heating_loop() that there was a start_heating() request
        self._run_heating_loop = True             # Flag to keep the heating thread alive
        self._reach_temperature_only_once = False # In case you want to reach a specific temperature only once (stop heating after reaching it)
        self._lock = threading.Lock()             # Thread will wait on the condition variable (so we can notify
        self._condition_var = threading.Condition(self._lock) # it on shutdown or other changes
        self._heating_loop_thread = threading.Thread(target=self.__heating_loop)
        self._heating_loop_thread.start()

        # Members related to temperature sensor check
        self._temperature_trend_waiting_time = config['heating']['temperature_trend_waiting_time'] # Time to wait before checking the temperature trend while heating
        self._temperature_trend_threshold = config['heating']['temperature_trend_threshold']       # Temperature inc/dec will be recognised if |delta_temp| >= threshold


    def start_heating(self, request_type, requested_by, target_temperature=None,
            temperature_hysteresis=0.5, duration=None, reach_temperature_only_once=False):
        """
        :param request_type: HeatingRequest (manual takes precedence over scheduled)
        :param requested_by: user name
        :param target_temperature: None or temperature to heat to
        :param target_hysteresis: hysteresis threshold
        :param duration: None or 
        """
        # Sanity checks:
        if self._is_terminating:
            return False, 'System wird gerade heruntergefahren.'

        sane, txt = type(self).sanity_check(request_type, target_temperature, 
            temperature_hysteresis, duration)
        if not sane:
            return False, txt

        if self._is_paused:
            if request_type == HeatingRequest.SCHEDULED:
                logging.getLogger().info("[Heating] Ignoring periodic heating request, because system is paused.")
                return False, 'Heizungsprogramme sind pausiert'
            else:
                logging.getLogger().info("[Heating] Manual request by '{:s}' overrides the current 'paused' state.".format(requested_by))
                self._is_paused = False

        # Acquire the lock, store this heat request.
        self._condition_var.acquire()
        if self._is_heating and self._is_manual_request and request_type == HeatingRequest.SCHEDULED:
            logging.getLogger().info("[Heating] Ignoring the periodic heating request by '{:s}', because there is a manual request by '{:s}' currently active.".format(
                requested_by, self._latest_request_by))
        else:
            self._latest_request_by = requested_by
            self._target_temperature = target_temperature
            self._temperature_hysteresis = temperature_hysteresis
            self._heating_duration = duration
            self._start_heating = True
            self._is_manual_request = request_type == HeatingRequest.MANUAL
            self._reach_temperature_only_once = (target_temperature is not None) and reach_temperature_only_once

        self._condition_var.notify()
        self._condition_var.release()
        return True, ''


    def stop_heating(self, requested_by):
        """Stops the heater (if currently active). Will be invoked by the user manually."""
        self._reach_temperature_only_once = False
        self._condition_var.acquire()
        if self._is_heating:
            logging.getLogger().info("[Heating] Stop heating as requested by '{:s}'".format(requested_by))
        self.__stop_heating()
        self._condition_var.notify()
        self._condition_var.release()

    
    def toggle_pause(self, requested_by):
        """Toggle pause (heating will be stopped if currently active)."""
        self._is_paused = not self._is_paused
        if self._is_paused:
            self.stop_heating(requested_by)
        return self._is_paused


    @property
    def is_paused(self):
        return self._is_paused


    def query_deconz_status(self):
        """:return: Verbose multi-line string."""
        return self._zigbee_gateway.query_deconz_details()


    def query_heating_state(self):
        """:return: is_heating(bool), list(lpd433.LpdDeviceState)"""
        return self._lpd433_gateway.query_heating()


    def query_temperature(self):
        """:return: list(raspbee.TemperatureState)"""
        return self._zigbee_gateway.query_temperature()


    def query_temperature_for_heating(self):
        """To adjust the heating, we need a reference temperature reading.
        However, sensors may be unreachable. Thus, we can configure a 
        "preferred reference temperature sensor order" which we iterate
        to obtain a valid reading. If no sensor is available, return None.

        :return: current_temperature(double) or None
        """
        return self._zigbee_gateway.query_temperature_for_heating()


    def __stop_heating(self):
        """You must hold the lock before calling this method!"""
        self._is_manual_request = False
        self._is_heating = False
        self._lpd433_gateway.turn_off()


    def run_blocking(self):
        self._heating_loop_thread.join()


    def shutdown(self):
        """Shut down gracefully."""
        logging.getLogger().info('[Heating] Stopping heating system...')
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
        reference_temperature_log = list()
        
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
                    logging.getLogger().info("[Heating] Starting BangBang to reach {:.1f} +/- {:.1f}° {}as requested by '{:s}'".format(
                        self._target_temperature, self._temperature_hysteresis, 
                        ' once (stop afterwards) ' if self._reach_temperature_only_once else '',
                        self._latest_request_by))
                else:
                    use_controller = False
                    logging.getLogger().info("[Heating] Starting manually (i.e. always on) as requested by '{:s}'".format(self._latest_request_by))

                if self._heating_duration is None:
                    end_time = None
                    if not self._reach_temperature_only_once:
                        logging.getLogger().info("[Heating] This heating request can only be stopped manually!")
                else:
                    end_time = time_utils.dt_offset(self._heating_duration)
                    logging.getLogger().info("[Heating] This heating request will end at {}".format(time_utils.format(end_time)))


            if self._is_heating:
                # Log temperature to see if room temperature actually increases
                current_temperature = self._zigbee_gateway.query_temperature_for_heating()
                reference_temperature_log.append(current_temperature) #TODO use circular buffer

                # Should we turn the heater on or off?
                if use_controller:
                    if current_temperature is None:
                        self._broadcaster.error('Ich konnte kein Thermometer abfragen - versuche jetzt, die Heizung einzuschalten.')
                        should_heat = True
                    else:
                        should_heat = self._controller.update(current_temperature)
                        if self._reach_temperature_only_once and not should_heat:
                            # If we want to heat the room up only once to reach a specific 
                            # temperature, we keep heating until the bang bang tells us to
                            # turn the heater off - this means, we reached temperature+hysteresis
                            # and now we can stop this heating job.
                            should_heat = False
                            self._is_heating = False
                            self._reach_temperature_only_once = False # Prevent future tasks (e.g. periodic onces from heating up only once)
                            logging.getLogger().info("[Heating] Heat up once: Stop heating as we reached {:.1f}° (target was {:.1f}°).".format(
                                    current_temperature,
                                    self._target_temperature
                                ))
                else:
                    should_heat = True

                # Is heating duration over?
                if end_time is not None and time_utils.dt_now() >= end_time:
                    self._is_heating = False
                    end_time = None
                    should_heat = False
                    logging.getLogger().info("[Heating] Heating request by '{:s}' has timed out, turning off the heater.".format(self._latest_request_by))

                # Tell the zigbee gateway to turn the heater on/off:
                if should_heat:
                    ret = self._lpd433_gateway.turn_on()
                else:
                    ret = self._lpd433_gateway.turn_off()

                # Error checking
                if not ret:
                    logging.getLogger().error('[Heating] LPD433 gateway could not execute turn {:s}'.format('on' if should_heat else 'off'))
                    self._broadcaster.error('Fehler beim {}schalten!'.format('Ein' if should_heat else 'Aus'))
                else:
                    # Check if heating is actually on/off (with LPD this should never
                    # yield an error - unless the RF transmission crashes)
                    is_heating, _ = self._lpd433_gateway.query_heating()
                    if is_heating is not None and is_heating != should_heat:
                        # Increase error count, but retry before broadcasting:
                        consecutive_errors += 1
                        logging.getLogger().error("[Heating] Status of LPD433 plugs ({}) doesn't match heating request ({})!".format(is_heating, should_heat))

                # Check whether temperature actually increases
                #TODO log should_heat along with reference temperature
                self.__check_temperature_trend(reference_temperature_log, should_heat)
            else:
                # We're not heating, so clear the temperature log
                reference_temperature_log = list()


            ## Note: LPD433 plugs don't transmit anything, so we cannot check if they
            ## are reachable/on/off...
            ## The following check was needed for ZigBee plugs (because they often
            ## disconnected)
            # # Check if all plugs are reachable
            # is_heating, plug_states = self._heating_system.query_heating()
            # if len(plug_states) == 0 or any([not plug.reachable for plug in plug_states]):
            #     consecutive_errors += 1

            # Report error if the plug didn't respond until now
            if consecutive_errors >= self._num_consecutive_errors_before_broadcast:
                self._broadcaster.error("Heizung reagiert nicht, bitte kontrollieren!")
                # Mute error broadcast for the next few retrys
                consecutive_errors = 0
            
            # Compute idle time
            now = time_utils.dt_now()
            idle_time = self._max_idle_time
            if end_time is not None and end_time > now:
                diff = end_time - now
                idle_time = min(self._max_idle_time, diff.total_seconds())

            # Send thread to sleep
            logging.getLogger().debug('[Heating] Heating loop goes to sleep for {} seconds'.format(idle_time))
            self._condition_var.wait(idle_time)

        self._condition_var.release()
        logging.getLogger().info('[Heating] Heating system has been shut down.')


    def __check_temperature_trend(self, reference_temperature_log, should_heat):
        trend_period = len(reference_temperature_log) * self._max_idle_time
        if trend_period >= self._temperature_trend_waiting_time:
            temperature_slope, determination_coefficient = \
                temperature_log.compute_temperature_trend(reference_temperature_log)
            if temperature_slope is not None and \
                (should_heat and temperature_slope < self._temperature_trend_threshold):
                logging.getLogger().error("[Heating] Temperature change ({:.3f}° with R-squared {:.3f}) too small despite heating for {} seconds".format(
                    temperature_slope, determination_coefficient, trend_period))
                broadcasting.MessageBroadcaster.instance().error('Temperatur steigt zu wenig an {:.3f}\u200a° innerhalb von {}'.format(
                    temperature_slope, time_utils.format_timedelta(datetime.timedelta(seconds=trend_period))))
            elif temperature_slope is not None: #TODO remove this debug output
                    broadcasting.MessageBroadcaster.instance().info("[Heating] Temperature change ({:.3f}° with R-squared {:.3f}), heating for {}".format(
                        temperature_slope, determination_coefficient, time_utils.format_timedelta(datetime.timedelta(seconds=trend_period))))
            
