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
from . import scheduling

"""Heating can be turned on via manual request or via a scheduled job."""
HeatingRequest = common.enum(MANUAL=1, SCHEDULED=2)



class Heating:
    __instance = None

    MIN_TEMPERATURE = 5.0
    MAX_TEMPERATURE = 30.0
    MIN_HYSTERESIS = 0.1
    MAX_HYSTERESIS = 10.0
    MAX_HEATING_DURATION = datetime.timedelta(hours=12)
    MIN_HEATING_DURATION = datetime.timedelta(minutes=15)


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


    @staticmethod
    def sanity_check(request_type, target_temperature, temperature_hysteresis, duration):
        if target_temperature is not None and \
            (target_temperature < Heating.MIN_TEMPERATURE or target_temperature > Heating.MAX_TEMPERATURE):
            return False, "Temperatur muss zwischen [{}, {}] liegen, nicht {}.".format(
                common.format_num('.1f', Heating.MIN_TEMPERATURE), 
                common.format_num('.1f', Heating.MAX_TEMPERATURE),
                common.format_num('.1f', target_temperature))

        if temperature_hysteresis < Heating.MIN_HYSTERESIS or temperature_hysteresis > Heating.MAX_HYSTERESIS:
            return False, "Hysterese muss zwischen [{}, {}] liegen, nicht {}.".format(
                common.format_num('.1f', Heating.MIN_HYSTERESIS), 
                common.format_num('.1f', Heating.MAX_HYSTERESIS), 
                common.format_num('.1f', temperature_hysteresis))

        if request_type == HeatingRequest.SCHEDULED and duration is None:
            return False, "Periodischer Heiztask muss eine Dauer angeben."

        if duration is not None and not isinstance(duration, datetime.timedelta):
            return False, "Falscher Datentyp für 'duration'."

        if duration is not None and duration > Heating.MAX_HEATING_DURATION:
            return False, "Heizdauer kann nicht länger als {} Stunden betragen.".format(
                Heating.MAX_HEATING_DURATION.total_seconds()/3600)

        if duration is not None and duration < Heating.MIN_HEATING_DURATION:
            return False, "Heizdauer kann nicht kürzer als {} Minuten betragen.".format(
                Heating.MIN_HEATING_DURATION.total_seconds/60)

        return True, ''


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
        self._latest_request_by = None   # Name of user who requested the most recent heating job
        self._num_consecutive_errors_before_broadcast = config['heating']['num_consecutive_errors_before_broadcast'] # Num of retrys before broadcasting a heating error
        self._max_idle_time = config['heating']['idle_time'] # Max. time to wait between __heating_loop() iterations
        self._is_terminating = False     # During shutdown, we want to prevent start_heating() calls
        self._start_heating = False      # Used to notify the __heating_loop() that there was a start_heating() request
        self._run_heating_loop = True    # Flag to keep the heating thread alive
        self._lock = threading.Lock()    # Thread will wait on the condition variable (so we can notify
        self._condition_var = threading.Condition(self._lock) # it on shutdown or other changes
        self._heating_loop_thread = threading.Thread(target=self.__heating_loop)
        self._heating_loop_thread.start()



    def start_heating(self, request_type, requested_by, target_temperature=None,
            temperature_hysteresis=0.5, duration=None):
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
            return sane, txt

        # Acquire the lock, store this heat request.
        self._condition_var.acquire()
        if self._is_manual_request and request_type == HeatingRequest.SCHEDULED:
            logging.getLogger().info("[Heating] Ignoring the periodic heating request by '{:s}', because there is a manual request by '{:s}' currently active.".format(
                requested_by, self._latest_request_by))
        else:
            self._latest_request_by = requested_by
            self._target_temperature = target_temperature
            self._temperature_hysteresis = temperature_hysteresis
            self._heating_duration = duration
            self._start_heating = True

        self._condition_var.notify()
        self._condition_var.release()
        return True, ''


    def stop_heating(self, requested_by):
        """Stops the heater (if currently active). Will be invoked by the user manually."""
        self._condition_var.acquire()
        if self._is_heating:
            logging.getLogger().info("[Heating] Stop heating as requested by '{:s}'".format(requested_by))
        self.__stop_heating()
        self._condition_var.notify()
        self._condition_var.release()


    def query_detailed_status(self):
        return 'TODO'
    # def query_detailed_status(self):
        # msg = list()
        # # Check connectivity:
        # msg.append('*Netzwerk:*')
        # # Home network
        # for name, host in self.known_hosts_local.items():
        #     reachable = hu.ping(host)
        #     msg.append('\u2022 {} [LAN] ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))

        # # WWW
        # for name, host in self.known_hosts_internet.items():
        #     reachable = hu.ping(host)
        #     msg.append('\u2022 {} ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
        # # Also check telegram
        # reachable = hu.check_url(self.known_url_telegram_api)
        # msg.append('\u2022 Telegram API ist {}'.format('online' if reachable else 'offline :bangbang:'))

        # msg.append('') # Empty line to separate text content
        
        # # Query RaspBee state
        # reachable = hu.check_url(self.known_url_raspbee)
        # if reachable:
        #     msg.append(self.raspbee_wrapper.query_full_state())
        # else:
        #     msg.append('*Heizung:*\n\u2022 deCONZ API ist offline :bangbang:')

        # # List all jobs:
        # msg.append('')
        # #TODO list other jobs
        # self.condition_var.acquire()
        # heating_jobs = [j for j in self.job_list if isinstance(j, HeatingJob)]
        # self.condition_var.release()
        # hjs = sorted(heating_jobs)
        # if len(hjs) == 0:
        #     msg.append('*Kein Heizungsprogramm*')
        # else:
        #     msg.append('*Heizungsprogramm:*')
        #     for j in hjs:
        #         if isinstance(j, PeriodicHeatingJob):
        #             next_run = hu.datetime_as_local(j.next_run)
        #             at_time = hu.time_as_local(j.at_time)
        #             duration_hrs = int(j.heating_duration.seconds/3600)
        #             duration_min = int((j.heating_duration.seconds - duration_hrs*3600)/60)
        #             msg.append('\u2022 {}, tgl. um {} für {:02d}\u200ah {:02d}\u200amin, nächster Start am `{}.{}.` ({})'.format(
        #                 'Aktiv' if j.is_running else 'Inaktiv',
        #                 at_time.strftime('%H:%M'), 
        #                 duration_hrs, duration_min,
        #                 next_run.day, 
        #                 next_run.month,
        #                 j.created_by
        #                 ))
        #         elif isinstance(j, ManualHeatingJob):
        #             duration_hrs = 0 if j.heating_duration is None else int(j.heating_duration.seconds/3600)
        #             duration_min = 0 if j.heating_duration is None else int((j.heating_duration.seconds - duration_hrs*3600)/60)
        #             msg.append('\u2022 {}, einmalig heizen{}{} ({})'.format(
        #                 'aktiv' if j.is_running else 'inaktiv',
        #                 ', {}\u200a°' if j.target_temperature is not None else '',
        #                 ', für {:02d}\u200ah {:02d}\u200amin'.format(duration_hrs, duration_min) if j.heating_duration is not None else '',
        #                 j.created_by
        #             ))
        
        # return '\n'.join(msg)


    def query_heating_state(self):
        """:return: is_heating(bool), list(raspbee.PlugState)"""
        return self._heating_system.query_heating()


    def query_temperature(self):
        """:return: list(raspbee.TemperatureState)"""
        return self._heating_system.query_temperature()


    def query_temperature_for_heating(self):
        """To adjust the heating, we need a reference temperature reading.
        However, sensors may be unreachable. Thus, we can configure a 
        "preferred reference temperature sensor order" which we iterate
        to obtain a valid reading. If no sensor is available, return None.

        :return: current_temperature(double) or None
        """
        return self._heating_system.query_temperature_for_heating()


    def __stop_heating(self):
        """You must hold the lock before calling this method!"""
        self._is_manual_request = False
        self._is_heating = False
        self._heating_system.turn_off()


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
                    logging.getLogger().info("[Heating] Starting BangBang to reach {:.1f} +/- {:.1f}° as requested by '{:s}'".format(
                        self._target_temperature, self._temperature_hysteresis, self._latest_request_by))
                else:
                    use_controller = False
                    logging.getLogger().info("[Heating] Starting manually (i.e. always on) as requested by '{:s}'".format(self._latest_request_by))

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
                    end_time = None
                    should_heat = False
                    logging.getLogger().info("[Heating] Heating request by '{:s}' has timed out, turning off the heater.".format(self._latest_request_by))

                # Tell the zigbee gateway to turn the heater on/off:
                if should_heat:
                    ret, msg = self._heating_system.turn_on()
                else:
                    ret, msg = self._heating_system.turn_off()

                # Error checking
                if not ret:
                    logging.getLogger().error('[Heating] RaspBee wrapper could not execute turn on/off command:\n' + msg)
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
            
            # Compute idle time
            now = time_utils.dt_now()
            idle_time = self._max_idle_time
            if end_time is not None and end_time > now:
                diff = end_time - now
                idle_time = min(self._max_idle_time, diff.total_seconds())

            # Send thread to sleep
            self._condition_var.wait(idle_time)

        self._condition_var.release()
        logging.getLogger().info('[Heating] Heating system has been shut down.')

