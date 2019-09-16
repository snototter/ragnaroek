#!/usr/bin/python
# coding=utf-8

# The heart of my home automation project

import datetime
import libconf
import logging
import threading
import time
import traceback

import helheimr_utils as hu
import helheimr_bot as hb
import helheimr_raspbee as hr
import helheimr_weather as hw

#TODO serialize periodic heating (and other) tasks:
# x,y = {'every':1, 'unit':'day'}, {'foo':'fighters'}
# z = (x,y)
# print(libconf.dumps({'heating_jobs':z}))

def to_duration(hours=0, minutes=0, seconds=0):
    return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)


class HeatingConfigurationError(Exception):
    """Used to indicate wrong configurations (e.g. temperature/duration,...)"""
    def __init__(self, message):
        self.message = message


class HeatingJob(hu.Job):
    @staticmethod
    def every(interval=1):
        return PeriodicHeatingJob(interval=interval)


    @staticmethod
    def manual(target_temperature=None, temperature_hysteresis=0.5, heating_duration=None, controller=None, created_by=None):
        mhj = ManualHeatingJob()
        return mhj.do_heat_up(target_temperature=target_temperature, 
            temperature_hysteresis=temperature_hysteresis, 
            heating_duration=heating_duration,
            controller=controller,
            created_by=created_by)


    def __init__(self, interval):
        super(HeatingJob, self).__init__(interval)
        self.controller = None # In case of errors, this task notifies the controller
        self.created_by = None # User name of task creator
        self.target_temperature = None # Try to reach this temperature +/- temperature_hysteresis (if set)
        self.temperature_hysteresis = None
        self.heating_duration = None # Stop heating after datetime.timedelta
        # Use the following condition variable instead of sleep() inside a heating job (upon 
        # stopping this task via self.keep_running=False, it will notify all waiting threads.
        self.lock = threading.Lock()
        self.cv_loop_idle = threading.Condition(self.lock)


    def do_heat_up(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None, controller=None, created_by=None):
        """Call this method to schedule this heating task."""
        # Sanity checks
        if controller is None:
            raise HeatingConfigurationError('Controller muss gesetzt werden, um die Heizung steuern zu können')
        if target_temperature is not None and (target_temperature < 10 or target_temperature > 30):
            raise HeatingConfigurationError('Temperatur muss zwischen 10 und 30 Grad eingestellt werden')
            if temperature_hysteresis is not None and ((target_temperature-temperature_hysteresis) < 10 or (target_temperature+temperature_hysteresis) > 30):
                raise HeatingConfigurationError('Temperatur +/- Hysterese muss zwischen 10 und 30 Grad eingestellt werden')
        #TODO check if tz aware or not
        if heating_duration is not None and heating_duration < datetime.timedelta(minutes=15):
            raise HeatingConfigurationError('Heizung muss für mindestens 15 Minuten eingeschalten werden')

        self.target_temperature = target_temperature
        self.temperature_hysteresis = temperature_hysteresis
        self.heating_duration = heating_duration
        self.controller = controller
        self.created_by = created_by
        return self.do(self.heating_loop)

    
    def __str__(self):
        return '{:s} for{:s}{:s}'.format('always on' if not self.target_temperature else '{:.1f}+/-{:.2f}°C'.format(self.target_temperature, self.temperature_hysteresis),
            'ever' if not self.heating_duration else ' {}'.format(self.heating_duration),
            '' if self.created_by is None else ' created by {}'.format(self.created_by))


    def heating_loop(self):
        self.was_started = True
        start_time = hu.datetime_now()
        if self.heating_duration is not None:
            end_time = start_time + self.heating_duration
        else:
            end_time = None

        if self.target_temperature is not None:
            use_temperature_controller = True
            bang_bang = hu.OnOffController()
            bang_bang.set_desired_value(self.target_temperature)
            bang_bang.set_hysteresis(self.temperature_hysteresis)
        else:
            use_temperature_controller = False

        self.cv_loop_idle.acquire()
        while self.keep_running:
            # #TODO heating is working, disabled for further implementation tests
            current_temperature = self.controller.query_temperature_for_heating()
            # if use_temperature_controller:
            #     if current_temperature is None:
            #         self.controller.broadcast_error('Ich konnte kein Thermometer abfragen - versuche, die Heizung einzuschalten.')
            #         should_heat = True
            #     else:
            #         should_heat = bang_bang.update(current_temperature)
            # else:
            #     should_heat = True

            # if should_heat:
            #     ret, msg = self.controller.heating_system.turn_on()
            # else:
            #     ret, msg = self.controller.heating_system.turn_off()

            # if not ret:
            #     logging.getLogger().error('RaspBee wrapper could not execute turn on/off command:\n' + msg)
            #     self.controller.broadcast_error('Heizung konnte nicht {}geschaltet werden:\n'.format('ein' if should_heat else 'aus') + msg)

            # TODO remove:
            dummy_msg = '{} heating {}for {} now, finish {}{}. Current temperature: {:.1f}°'.format(
                'Manual' if isinstance(self, ManualHeatingJob) else 'Periodic',
                ' to {}+/-{} °C '.format(self.target_temperature, self.temperature_hysteresis) if self.target_temperature is not None else '',
                hu.datetime_difference(start_time, hu.datetime_now()),
                'at {}'.format(end_time) if end_time is not None else 'never',
                '' if self.created_by is None else ', created by {}'.format(self.created_by),
                current_temperature
                )
            print(dummy_msg)
            # self.controller.broadcast_warning(dummy_msg)#TODO remove

            if end_time is not None and hu.datetime_now() >= end_time:
                break
            self.cv_loop_idle.wait(timeout=60)#TODO adjust timeout! - maybe query every 2-5 minutes???
        self.cv_loop_idle.release
        self.keep_running = False

        logging.getLogger().info('[ManualHeatingJob] Terminating "{}" after {}'.format(self, hu.datetime_difference(start_time, hu.datetime_now())))
        ret, msg = self.controller.heating_system.turn_off()
        if not ret:
            logging.getLogger().error('Could not turn off heating after finishing this heating job:\n' + msg)
            #TODO notify user

#TODO make separate stop_without_turning_off() - set a flag to prevent turning the heater off if we're inside add_manual_job (since the manual job may start the heater pretty soon (or turn it off itself...))
    def stop(self):
        """Stop heating (if currently active). Does NOT delete the task."""
        if self.keep_running:
            self.keep_running = False
            self.cv_loop_idle.acquire()
            self.cv_loop_idle.notifyAll()
            self.cv_loop_idle.release()
            self.worker_thread.join(timeout=10)


# TODO from libconf, to libconf https://github.com/Grk0/python-libconf
# return a dict for serialization
class PeriodicHeatingJob(HeatingJob):  
    def _schedule_next_run(self):
        if self.heating_duration is None:
            raise hu.ScheduleValueError('PeriodicHeatingJob must have a duration')
        if self.at_time is None:
            raise hu.ScheduleValueError('PeriodicHeatingJob can only occur at a specific time. Specify "at_time"')

        super(PeriodicHeatingJob, self)._schedule_next_run()

        if self.heating_duration >= self.period:
            raise hu.IntervalError("PeriodicHeatingJob's duration ({}) must be less than the scheduled interval ({})".format(self.heating_duration, self.period))


    def __str__(self):
        return "PeriodicHeatingJob: every {}{}{}, {}".format(self.interval if self.interval > 1 else '',
                 self.unit[:-1] if self.interval == 1 else self.unit,
                 '' if self.at_time is None else ' at {}'.format(self.at_time),
                 super(PeriodicHeatingJob, self).__str__())


    def overlaps(self, other):
        # Periodic heating jobs are (currently) assumed to run each day at a specific time
        start_this = datetime.datetime.combine(datetime.datetime.today(), self.at_time)
        end_this = start_this + self.heating_duration
        start_other = datetime.datetime.combine(datetime.datetime.today(), other.at_time)
        end_other = start_other + other.heating_duration
        
        if (end_other < start_this) or (start_other > end_this):
            return False
        return True


    def to_dict(self):
        """Return a dict for serialization via libconf."""
        d = {
            'type' : 'periodic',
            'every': self.interval,
            'unit': self.unit,
            'at': self.at_time, # Periodic heating job MUST have an at_time #TODO FIXME at_time is hu.time-as_utc: need to store it as local time :-/
            'duration': str(self.heating_duration)
        }
        if self.target_temperature is not None:
            d['temperature'] = self.target_temperature
            if self.temperature_hysteresis is not None:
                d['hysteresis'] = self.temperature_hysteresis
        return d
    
    @staticmethod
    def from_libconf(self, cfg):
        if cfg['type'] != 'periodic':
            raise RuntimeError('Cannot instantiate a PeriodicHeatingJob from type "{}" - it must be "periodic"!'.format(cfg['type']))
        interval = cfg['every']
        unit = cfg['unit']
        at = cfg['at']
        duration = cfg['duration']
        print('TODO TODO TODO TODO: ', interval, unit, at, duration)
        #TODO build job and return
        return None



class ManualHeatingJob(HeatingJob):
    def __init__(self):#, target_temperature=None, temperature_hysteresis=None, duration=None):
        # Set a dummy interval of 72 hours (we will start the task immediately)
        super(ManualHeatingJob, self).__init__(720) 
            # target_temperature, temperature_hysteresis, duration)
        self.unit = 'hours'
        self.was_started = False # Indicates whether this job has been started (as manual jobs will only be run once)
        #self.next_run = hu.datetime_now() #next_run is used to sleep in the event loop, don't modify it :-p
        #self.start() # Start immediately

    def __lt__(self, other):
        """Manual heating jobs should be handled before periodic ones"""
        if isinstance(other, PeriodicHeatingJob):
            return True
        else:
            return self.next_run < other.next_run #TODO check sorting of manual + periodic heating jobs!
        
    def __str__(self):
        return "ManualHeatingJob: " + super(ManualHeatingJob, self).__str__()

    
    @property
    def should_be_removed(self):
        """Remove after we finished"""
        return self.worker_thread is not None and not self.keep_running


    @property
    def should_run(self):
        # Only return true until this job has been started once!
        return True and not self.was_started


class HelheimrController:
    def __init__(self):
        # The wrapper which is actually able to turn stuff on/off
        ctrl_cfg = hu.load_configuration('configs/ctrl.cfg')
        self.raspbee_wrapper = hr.RaspBeeWrapper(ctrl_cfg)

        # We use a condition variable to sleep during scheduled tasks (in case we need to wake up earlier)
        self.lock = threading.Lock()
        self.condition_var = threading.Condition(self.lock)

        self.logger = logging.getLogger() # Keep consistent logs...

        self.run_loop = True # Flag to abort the scheduling/main loop
        self.job_list = list() # List of scheduled/manually inserted jobs

        self.poll_interval = 30 #TODO config
        self.active_heating_job = None # References the currently active heating job (for convenience)

        self.worker_thread = threading.Thread(target=self._scheduling_loop) # The scheduler runs in a separate thread
        self.worker_thread.start()

        #TODO dummy jobs, replace by load-from-file:
        # # # self._add_manual_heating_job(None, None, datetime.timedelta(seconds=10))
        # # # self._add_manual_heating_job(23, 0.5, None)
        # # try:
        # #     self.job_list.append(HeatingJob.every(10).seconds.do_heat_up(target_temperature=20.0, temperature_hysteresis=0.5, heating_duration=to_duration(0, 0, 5)))
        # #     self.job_list.append(HeatingJob.every(4).seconds.do_heat_up(target_temperature=20.0, temperature_hysteresis=0.5, heating_duration=to_duration(0, 0, 5)))
        # # except Exception as e:
        # #     print('This error was expected: ', e)
        # #     pass
        # self._add_periodic_heating_job(target_temperature=None, temperature_hysteresis=0.5, 
        #     heating_duration=datetime.timedelta(hours=2),
        #     day_interval=1, at_hour=6, at_minute=30)
        # self._add_periodic_heating_job(target_temperature=None, temperature_hysteresis=0.5, 
        #     heating_duration=datetime.timedelta(hours=3),
        #     day_interval=1, at_hour=7, at_minute=59)

        # # # self.job_list.append(hu.Job.every(5).seconds.do(dummy_job, 5))
        # # # self.job_list.append(hu.Job.every(10).seconds.do(dummy_job, 10))
        # # # self.job_list.append(hu.Job.every().minute.do(self.stop))
        # # # self.job_list.append(ManualHeatingJob(controller=self, target_temperature=None, 
        # # #     temperature_hysteresis=None, duration=datetime.timedelta(seconds=10)))
        # # # self.job_list.append(ManualHeatingJob(controller=self, target_temperature=23, 
        # #     # temperature_hysteresis=0.5))
        # # # self.job_list.append(hu.Job.every(3).seconds.do(self.dummy_stop))
        #TODO Create a dummy heating job:
        self.filename_job_list = 'configs/scheduled-jobs.cfg'
        start_time = (datetime.datetime.now() + datetime.timedelta(seconds=10)).time()
        self._add_periodic_heating_job(27.8, 0.8, to_duration(hours=1), 1, at_hour=start_time.hour, at_minute=start_time.minute, at_second=start_time.second, created_by='Helheimr')
        self.serialize_jobs()

        #TODO test serializing periodic jobs:
        # import libconf
        # print(libconf.dumps(self.job_list[-1].to_dict()))

        self.condition_var.acquire()
        self.job_list.append(hu.Job.every(120).seconds.do(self.stop))#TODO remove
        self.condition_var.notify()
        self.condition_var.release()


        if not hu.check_internet_connection():
            #TODO weather won't work, telegram neither - check what happens!
            #TODO add warning message to display
            self.logger.error('No internet connection!')
        # else:
        #     self.logger.info('Yes, WE ARE ONLINE!') #TODO remove...

        # Weather forecast/service wrapper
        weather_cfg = hu.load_configuration('configs/owm.cfg')
        self.weather_service = hw.WeatherForecastOwm(weather_cfg)

        # Telegram bot for notifications and user input (heat on-the-go ;-)
        bot_cfg = hu.load_configuration('configs/bot.cfg')
        self.telegram_bot = hb.HelheimrBot(bot_cfg, self)

        self.telegram_bot.start()

        # Collect hosts we need to contact (weather service, telegram, local IPs, etc.)
        self.known_hosts_local = self._load_known_hosts(ctrl_cfg['network']['local'])
        self.known_hosts_internet = self._load_known_hosts(ctrl_cfg['network']['internet'])
        self.known_url_telegram_api = 'https://t.me/' + bot_cfg['telegram']['bot_name']
        self.known_url_raspbee = self.raspbee_wrapper.api_url

    
    def _load_known_hosts(self, libconf_attr_dict):
        return {k:libconf_attr_dict[k] for k in libconf_attr_dict}


    @property
    def heating_system(self):
        return self.raspbee_wrapper


    def _broadcast_message(self, text, msg_type):
        #TODO broadcast to display!!!
        if msg_type == 'info':
            telegram_msg = text
        elif msg_type == 'warning':
            telegram_msg = ':warning: ' + text
        elif msg_type == 'error':
            telegram_msg = ':bangbang: ' + text
        else:
            raise RuntimeError('Invalid message type "{}"'.format(msg_type))

        self.telegram_bot.broadcast_message(telegram_msg)


    def broadcast_info(self, text):
        self._broadcast_message(text, 'info')

    def broadcast_warning(self, text):
        self._broadcast_message(text, 'warning')

    def broadcast_error(self, text):
        self._broadcast_message(text, 'error')
    

    def query_heating_state(self):
        """:return: is_heating(bool), list(PlugState)"""
        return self.heating_system.query_heating()


    def query_temperature(self):
        """:return: list(TemperatureState)"""
        return self.heating_system.query_temperature()


    def query_temperature_for_heating(self):
        """To adjust the heating, we need a reference temperature reading.
        However, sensors may be unreachable. Thus, we can configure a 
        "preferred reference temperature sensor order" which we iterate
        to obtain a valid reading. If no sensor is available, return None.
        """
        return self.heating_system.query_temperature_for_heating()


    def query_weather_forecast(self):
        """:return: helheimr_weather.WeatherForecast object"""
        return self.weather_service.query()


    def query_detailed_status(self):
        msg = list()
        # Check connectivity:
        msg.append('*Netzwerk:*')
        # Home network
        for name, host in self.known_hosts_local.items():
            reachable = hu.ping(host)
            msg.append('\u2022 {} [LAN] ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))

        # WWW
        for name, host in self.known_hosts_internet.items():
            reachable = hu.ping(host)
            msg.append('\u2022 {} ist {}'.format(name, 'online' if reachable else 'offline :bangbang:'))
        # Also check telegram
        reachable = hu.check_url(self.known_url_telegram_api)
        msg.append('\u2022 Telegram API ist {}'.format('online' if reachable else 'offline :bangbang:'))

        msg.append('') # Empty line to separate text content
        
        # Query RaspBee state
        reachable = hu.check_url(self.known_url_raspbee)
        if reachable:
            msg.append(self.raspbee_wrapper.query_full_state())
        else:
            msg.append('*Heizung:*\n\u2022 deCONZ API ist offline :bangbang:')
        
        return '\n'.join(msg)


    def stop(self):
        self.run_loop = False
        self.condition_var.acquire()
        self.condition_var.notify() # Wake up controller/scheduler
        self.condition_var.release()
        self.worker_thread.join()

        #TODO cancel all tasks, turn off heating!

        # Send shutdown message
        if self.telegram_bot:
            self.telegram_bot.stop()


    def join(self):
        """Block on the controller's scheduling thread."""
        self.worker_thread.join()


    @property
    def next_run(self):
        """:return: Datetime object indicating the time of the next scheduled job."""
        if len(self.job_list) == 0:
            return None
        return min(self.job_list).next_run


    @property
    def idle_time(self):
        """:return: Idle time in seconds before the next (scheduled) job is to be run."""
        return hu.datetime_difference(hu.datetime_now(), self.next_run).total_seconds()

#TODO configure perdiodic task from bot:
    # def schedule_heating(self, day_interval=1, at_hour=6, at_minute=30, target_temperature=None, temperature_hysteresis=0.5, heating_duration=to_duration(hours=2), created_by=None).
        # success ... self._add_periodic_heating_job()
        # if success:
        # self.serialize()


    def _cancel_job(self, job):
        # Delete a registered job - make sure to acquire the lock first!
        try:
            self.logger.info('[HelheimrController] Removing job "{}"'.format(job))
            if job == self.active_heating_job:
                self.active_heating_job = None
            self.job_list.remove(job)
        except ValueError:
            self.logger.error('[HelheimrController] Could not cancel job "{}"'.format(job))


    def turn_on_manually(self, target_temperature=None, temperature_hysteresis=0.5, duration=None, created_by=None):
        """TODO
        duration datetime.timedelta
        """
        try:
            self._add_manual_heating_job(target_temperature, temperature_hysteresis, duration, created_by)
            return True, 'Befehl wurde an Heizungssteuerung weitergeleitet.'
        except HeatingConfigurationError as e:
            return False, e.message
        except: # TODO custom exception (heatingconfigerror, nur e.message/text anzeigen) vs general exception
            err_msg = traceback.format_exc(limit=3)
            return False, '[Traceback]: '+err_msg # TODO traceback


    def turn_off_manually(self, user_name):
        if self.active_heating_job:
            self.logger.info('[HelheimrController] Stop heating due to user "{}" request'.format(user_name))
            self.active_heating_job.stop()
            return True, 'Heizung wurde ausgeschaltet'
        else:
            return False, 'Heizung ist nicht eingeschaltet'

    
    def _add_manual_heating_job(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None, created_by=None):
        mhj = HeatingJob.manual(target_temperature=target_temperature, 
            temperature_hysteresis=temperature_hysteresis, 
            heating_duration=heating_duration,
            controller=self,
            created_by=created_by)
        ret = False
        try:
            self.condition_var.acquire()
            if self.active_heating_job is not None and self.active_heating_job.is_running:
                self.logger.warning("[HelheimrController] There's an active heating job, I'm stopping it right now")
                self.active_heating_job.stop()
            self.active_heating_job = None
                
                # upon error return prematurely (but condvar.release()!)
            self.logger.info("[HelheimrController] Adding a ManualHeatingJob ({}) to my task list.".format(mhj))
            self.job_list.append(mhj)
            ret = True
        except:
            self.logger.error('[HelheimrController] Error while adding manual heating job {}:\n'.format(mhj) + traceback.format_exc(limit=3))
        finally:
            self.condition_var.notify()
            self.condition_var.release()
        return ret


    def _add_periodic_heating_job(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None,
            day_interval=1, at_hour=6, at_minute=0, at_second=0, created_by=None):
        self.condition_var.acquire()
        try: 
            job = HeatingJob.every(day_interval).days.at(
                '{:02d}:{:02d}:{:02d}'.format(at_hour, at_minute, at_second)).do_heat_up(
                    controller=self,
                    target_temperature=target_temperature, temperature_hysteresis=temperature_hysteresis, 
                    heating_duration=heating_duration,
                    created_by=created_by)
            if any([j.overlaps(job) for j in self.job_list]):
                raise HeatingConfigurationError('The requested periodic job "{}" overlaps with an existing one!'.format(job))
            self.job_list.append(job)
            self.condition_var.notify()
        except:
            #TODO separate catch for HeatingConfiguration Error
            #TODO print stack trace!!!!!!
            err_msg = traceback.format_exc(limit=3)
            print('\nOHOHOHOHOHOH TODO Error:\n', err_msg)#TODO
        finally:
            self.condition_var.release()


    def _scheduling_loop(self):
        self.condition_var.acquire()
        while self.run_loop:
            # Filter finished one-time jobs
            for job in [job for job in self.job_list if job.should_be_removed]:
                self._cancel_job(job)

            # Query job list for scheduled/active jobs
            runnable_jobs = (job for job in self.job_list if job.should_run)
            self.logger.info('[HelheimrController] Checking job list - known jobs are:\n' + \
                '\n'.join(map(str, self.job_list))) #TODO add time between loop iterations!
            for job in sorted(runnable_jobs):
                # If there is a job which is not running already, start it.
                if not job.is_running:
                    self.logger.info('[HelheimrController] Starting job "{}"'.format(job))
                    if isinstance(job, HeatingJob):
                        # There must only be one heating job active!
                        #TODO but manual takes preference over scheduled
                        if self.active_heating_job is None or not self.active_heating_job.is_running:
                            self.active_heating_job = job
                            job.start()
                        else:
                            self.logger.warning("[HelheimrController] There's already a heating job '{}' running. I'm ignoring '{}'".format(
                                self.active_heating_job, job))
                            #TODO implement job.skip() - calls _schedule_next()
                    else:
                        job.start()

            
            poll_interval = self.poll_interval if not self.job_list else min(self.poll_interval, self.idle_time)
            self.logger.info('[HelheimrController] Going to sleep for {:.1f} seconds'.format(max(1,poll_interval)))
            # print('Going to sleep for {:.1f} sec'.format(poll_interval))
            ret = self.condition_var.wait(timeout=max(1,poll_interval))
            #TODO maybe remove output
            if ret:
                self.logger.info('[HelheimrController] Woke up due to notification!'.format(max(1,poll_interval)))
        
        #######################################################################
        # Gracefully shut down:
        self.condition_var.release()
        self.logger.info('[HelheimrController] Shutting down control loop, terminating active jobs.')

        # Tear down all active jobs:
        for job in self.job_list:
            if job.is_running:
                self.logger.info('[HelheimrController] Terminating "{}".'.format(job))
                job.stop()
        self.logger.info('[HelheimrController] Clean up done, goodbye!')

    def deserialize_jobs(self):
        #TODO implement
        pass 

    def serialize_jobs(self):
        self.condition_var.acquire()
        # Each job class (e.g. periodic heating) has a separate group within the configuration file:
        phjs = [j.to_dict() for j in self.job_list if isinstance(j, PeriodicHeatingJob)] # Periodic heating jobs
        #TODO add other tasks (such as periodic display update) too!
        self.condition_var.release()
        try:
            lcdict = {
                    'periodic_heating' : phjs
                }
            with open(self.filename_job_list, 'w') as f:
                # f.write(libconf.dumps(lcdict))
                libconf.dump(lcdict, f)
            pass
        except:
            err_msg = traceback.format_exc(limit=3)
            #TODO broadcast error!

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
    
    controller = HelheimrController()
    try:
        controller.join()
    except KeyboardInterrupt:
        controller.stop()
    #TODO shut down heating