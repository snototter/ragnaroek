#!/usr/bin/python
# coding=utf-8

# The heart of my home automation project

import datetime
import libconf
import logging
import threading
import time
import traceback

import helu as hu
import helheimr_bot as hb
import helheimr_raspbee as hr
import helheimr_weather as hw

#TODO broadcast error if temperature does not increase despite heating!!! (thermal runaway)

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
        self.turn_off_heating_upon_exit = True
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


    def skip_one_run(self):
        # Needed e.g. if a manual heating request is active while a scheduled
        # periodic heating task would be started. Here, we ignore/skip the
        # periodic task
        self.next_run += self.period


    def heating_loop(self):
        self.was_started = True

        # Compute (optional) end time:
        # * Periodic heating jobs have at_time set (which is the expected start time).
        # * Manual heating jobs don't have an at_time (but may have a duration).
        start_time = hu.datetime_now() if self.at_time is None else hu.datetime_as_utc(datetime.datetime.combine(datetime.datetime.today(), self.at_time))
        if self.heating_duration is not None:
            end_time = start_time + self.heating_duration
        else:
            end_time = None

        # Check if we need a controller.
        if self.target_temperature is not None:
            use_temperature_controller = True
            bang_bang = hu.OnOffController()
            bang_bang.set_desired_value(self.target_temperature)
            bang_bang.set_hysteresis(self.temperature_hysteresis)
        else:
            use_temperature_controller = False

#https://stackoverflow.com/questions/4151320/efficient-circular-buffer
#TODO controller should log temperature in a circular buffer, direction_with_hysteresis (increasing, decreasing, stays the same over the past X minutes)
        consecutive_errors = 0 #TODO we may want to retry turning the heater on/off a few times before aborting this task
        self.cv_loop_idle.acquire()
        while self.keep_running:
            current_temperature = self.controller.query_temperature_for_heating()
            if use_temperature_controller:
                if current_temperature is None:
                    self.controller.broadcast_error('Ich konnte kein Thermometer abfragen - versuche, die Heizung einzuschalten.')
                    should_heat = True
                else:
                    should_heat = bang_bang.update(current_temperature)
            else:
                should_heat = True

            if should_heat:
                ret, msg = self.controller.heating_system.turn_on()
            else:
                ret, msg = self.controller.heating_system.turn_off()

            if not ret:
                logging.getLogger().error('RaspBee wrapper could not execute turn on/off command:\n' + msg)
                self.controller.broadcast_error('Heizung konnte nicht {}geschaltet werden:\n'.format('ein' if should_heat else 'aus') + msg)

            # TODO remove:
            dummy_msg = '\n[!!!] [!!!] [!!!] {} heating {}for {} now, finish {}{}. Current temperature: {:.1f}°\n'.format(
                'Manual' if isinstance(self, ManualHeatingJob) else 'Periodic',
                ' to {}+/-{} °C '.format(self.target_temperature, self.temperature_hysteresis) if self.target_temperature is not None else '',
                hu.datetime_difference(start_time, hu.datetime_now()),
                'at {}'.format(hu.datetime_as_local(end_time)) if end_time is not None else 'never',
                '' if self.created_by is None else ', created by {}'.format(self.created_by),
                current_temperature
                )
            print(dummy_msg)

            # Check if heating is actually on/off
            is_heating, _ = self.controller.query_heating_state()
            if is_heating is not None and is_heating != should_heat:
                consecutive_errors += 1
                self.controller.broadcast_error("Heizung reagiert nicht - Status '{}', sollte aber '{}' sein!".format('ein' if is_heating else 'aus', 'ein' if should_heat else 'aus'))
            else:
                consecutive_errors = 0
            
            # if consecutive_errors >= TODO MAX RETRIES
                # self.keep_running = False #TODO should we retry?????
                # break

            if end_time is not None and hu.datetime_now() >= end_time:
                self.keep_running = False
                break
            self.cv_loop_idle.wait(timeout=20)#TODO adjust timeout! - maybe query every 2-5 minutes???
            
        self.cv_loop_idle.release

        logging.getLogger().info('[HeatingJob] Terminating "{}" after {}'.format(self, hu.datetime_difference(start_time, hu.datetime_now())))
        if self.turn_off_heating_upon_exit:
            ret, msg = self.controller.heating_system.turn_off()
            if not ret:
                logging.getLogger().error('Could not turn off heating after finishing this heating job:\n' + msg)
                self.controller.broadcast_error('Fehler beim Beenden des aktuellen Heizprogramms:\n' + msg)


    def stop(self):
        """Stop heating (if currently active). Does NOT delete the task."""
        if self.keep_running:
            self.keep_running = False
            self.cv_loop_idle.acquire()
            self.cv_loop_idle.notifyAll()
            self.cv_loop_idle.release()
            self.worker_thread.join(timeout=10)


    def stop_without_turning_off(self):
        """Stops the currently active job but doesn't turn off the heater.
        Use if this job is replaced by another one (which will start immediately)
        to prevent unnecessarily changing the state of the power plug."""
        self.turn_off_heating_upon_exit = False
        self.stop()


class PeriodicHeatingJob(HeatingJob):  
    def _schedule_next_run(self):
        if self.heating_duration is None:
            raise hu.ScheduleValueError('PeriodicHeatingJob must have a duration')
        if self.at_time is None:
            raise hu.ScheduleValueError('PeriodicHeatingJob can only occur at a specific time. Specify "at_time"')

        first_time = self.last_run is None
        super(PeriodicHeatingJob, self)._schedule_next_run()
#TODO broadcast to specific IDs (config file) - only bug me with errors/warnings...
        # Adjust schedule if the controller starts within a configured heating period:
        start_time = datetime.datetime.combine(datetime.datetime.today(), self.at_time)
        end_time = start_time + self.heating_duration
        now = hu.datetime_now()
        if first_time and (start_time <= now) and (now < end_time):
            # The generic job class was scheduled for tomorrow (since it is 
            # not aware of a job's duration). Thus, reschedule for today, i.e. now!
            self.next_run -= self.period

        if self.heating_duration >= self.period:
            raise hu.IntervalError("PeriodicHeatingJob's duration ({}) must be less than the scheduled interval ({})".format(self.heating_duration, self.period))


    def __str__(self):
        return "PeriodicHeatingJob: every {}{}{}, {}".format(self.interval if self.interval > 1 else '',
                 self.unit[:-1] if self.interval == 1 else self.unit,
                 '' if self.at_time is None else ' at {}'.format(hu.time_as_local(self.at_time)),
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
            'day_interval': self.interval,
            'at': hu.time_as_local(self.at_time).strftime('%H:%M:%S'), # Store as local time
            'duration': str(self.heating_duration)
        }
        if self.target_temperature is not None:
            d['temperature'] = self.target_temperature
            if self.temperature_hysteresis is not None:
                d['hysteresis'] = self.temperature_hysteresis
        if self.created_by is not None:
            d['created_by'] = self.created_by
        return d

    
    @staticmethod
    def from_libconf(cfg, controller):
        if cfg['type'] != 'periodic':
            raise RuntimeError('Cannot instantiate a PeriodicHeatingJob from type "{}" - it must be "periodic"!'.format(cfg['type']))

        day_interval = cfg['day_interval']
        # The generic Job class expects at_time given as a string (but we have to take care of UTC/localtime).
        # The configuration file uses localtime:
        at = cfg['at']
        # # at_utc = hu.time_as_utc(datetime.datetime.strptime(cfg['at'], '%H:%M:%S').timetz())
        # # at = str(at_utc) # should be loaded as string! hu.time_as_utc(datetime.datetime.strptime(cfg['at'], '%H:%M:%S').time())

        # Parse duration string (using strptime doesn't work if duration > 24h)
        d = cfg['duration'].split(':')
        hours = int(d[0])
        minutes = 0 if len(d) == 1 else int(d[1])
        seconds = 0 if len(d) == 2 else int(d[2])
        duration = datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)

        def val_or_none(k):
            return cfg[k] if k in cfg else None
        
        temperature = val_or_none('temperature')
        hysteresis = val_or_none('hysteresis')
        created_by = val_or_none('created_by')

        # def p(k):
        #     print(k, type(k))
        # p(temperature)
        # p(hysteresis)
        # p(created_by)
        # p(at)
        # p(duration)
        # p(day_interval)
        
        job = HeatingJob.every(day_interval).days.at(at).do_heat_up(
                controller=controller,
                target_temperature=temperature, temperature_hysteresis=hysteresis, 
                heating_duration=duration,
                created_by=created_by)
        return job



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
            return self.next_run < other.next_run
        
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

#FIXME der zweite Job (10sec nach Start läuft nicht (daemon thread!!!))
class HelheimrController:
    JOB_LIST_CONFIG_KEY_PERIODIC_HEATING = 'periodic_heating_jobs'
    
    def __init__(self):
        # The wrapper which is actually able to turn stuff on/off
        ctrl_cfg = hu.load_configuration('configs/ctrl.cfg')
        # self.raspbee_wrapper = hr.DummyRaspBeeWrapper(ctrl_cfg)
        self.raspbee_wrapper = hr.RaspBeeWrapper(ctrl_cfg) #TODO/FIXME!!!!!!

        # We use a condition variable to sleep during scheduled tasks (in case we need to wake up earlier)
        self.lock = threading.Lock()
        self.condition_var = threading.Condition(self.lock)

        self.logger = logging.getLogger() # Keep consistent logs...

        self.run_loop = True # Flag to abort the scheduling/main loop
        self.job_list = list() # List of scheduled/manually inserted jobs

        self.poll_interval = ctrl_cfg['scheduler']['idle_time']
        self.active_heating_job = None # References the currently active heating job (for convenience)


        self.temperature_readings = hu.circularlist(100) #TODO make param

        self.worker_thread = threading.Thread(target=self._scheduling_loop) # The scheduler runs in a separate thread
        self.worker_thread.start()


        #TODO Create a dummy heating job starting in 10 seconds:
        # start_time = (datetime.datetime.now() + datetime.timedelta(seconds=10)).time()
        # self._add_periodic_heating_job(27.8, 0.8, to_duration(hours=1), 1, at_hour=start_time.hour, at_minute=start_time.minute, at_second=start_time.second, created_by='Helheimr')

        # #TODO remove dummy job:
        # self.condition_var.acquire()
        # self.job_list.append(hu.Job.every(120).seconds.do(self.stop))#TODO remove
        # self.condition_var.notify()
        # self.condition_var.release()

        if not hu.check_internet_connection():
            #TODO weather won't work, telegram neither - check what happens!
            #TODO add warning message to display
            self.logger.error('No internet connection!')
        # else:
        #     self.logger.info('Yes, WE ARE ONLINE!')

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

        # Load pre-configured heating jobs
        self.filename_job_list = 'configs/scheduled-jobs.cfg'
        self.deserialize_jobs()

    
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

        # List all jobs:
        msg.append('')
        #TODO list other jobs
        self.condition_var.acquire()
        heating_jobs = [j for j in self.job_list if isinstance(j, HeatingJob)]
        self.condition_var.release()
        hjs = sorted(heating_jobs)
        if len(hjs) == 0:
            msg.append('*Kein Heizungsprogramm*')
        else:
            msg.append('*Heizungsprogramm:*')
            for j in hjs:
                if isinstance(j, PeriodicHeatingJob):
                    next_run = hu.datetime_as_local(j.next_run)
                    at_time = hu.time_as_local(j.at_time)
                    duration_hrs = int(j.heating_duration.seconds/3600)
                    duration_min = int((j.heating_duration.seconds - duration_hrs*3600)/60)
                    msg.append('\u2022 {}, tgl. um {} für {:02d}\u200ah {:02d}\u200amin, nächster Start am `{}.{}.`'.format(
                        'Aktiv' if j.is_running else 'Inaktiv',
                        at_time.strftime('%H:%M'), 
                        duration_hrs, duration_min,
                        next_run.day, 
                        next_run.month
                        ))
                elif isinstance(j, ManualHeatingJob):
                    duration_hrs = 0 if j.heating_duration is None else int(j.heating_duration.seconds/3600)
                    duration_min = 0 if j.heating_duration is None else int((j.heating_duration.seconds - duration_hrs*3600)/60)
                    msg.append('\u2022 {}, einmalig heizen{}{}'.format(
                        'aktiv' if j.is_running else 'inaktiv',
                        ', {}\u200a°' if j.target_temperature is not None else '',
                        ', für {:02d}\u200ah {:02d}\u200amin'.format(duration_hrs, duration_min) if j.heating_duration is not None else ''
                    ))
        
        return '\n'.join(msg)


    def stop(self):
        self.run_loop = False
        self.condition_var.acquire()
        self.condition_var.notify() # Wake up controller/scheduler
        self.condition_var.release()
        self.worker_thread.join()

        #TODO cancel all tasks
        #TODO turn off heating!

        # Send shutdown message
        if self.telegram_bot:
            self.telegram_bot.stop()


    def shutdown(self):
        self.stop()
        #TODO shutdown pi!


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
        """
        Manually turning on replaces any active task.
        target_temperature & hysteresis is float
        duration is datetime.timedelta
        created_by is user name
        """
        try:
            self._add_manual_heating_job(target_temperature, temperature_hysteresis, duration, created_by)
            return True, 'Befehl wurde an Heizungssteuerung weitergeleitet.'
        except HeatingConfigurationError as e:
            return False, e.message
        except:
            err_msg = traceback.format_exc(limit=3)
            return False, '[Traceback]: '+err_msg


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
                self.active_heating_job.stop_without_turning_off()
            self.active_heating_job = None
                
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
        job = HeatingJob.every(day_interval).days.at(
                '{:02d}:{:02d}:{:02d}'.format(at_hour, at_minute, at_second)).do_heat_up(
                controller=self,
                target_temperature=target_temperature, temperature_hysteresis=temperature_hysteresis, 
                heating_duration=heating_duration,
                created_by=created_by)
        return self._add_periodic_heating_job_object(job)
        

    def _add_periodic_heating_job_object(self, periodic_heating_job):
        ret_val = False
        self.condition_var.acquire()
        try:
            if any([j.overlaps(periodic_heating_job) for j in self.job_list]):
                raise HeatingConfigurationError('The requested periodic job "{}" overlaps with an existing one!'.format(periodic_heating_job))
            self.job_list.append(periodic_heating_job)
            self.condition_var.notify()
            ret_val = True
        except HeatingConfigurationError as e:
            self.logger.error('[HelheimrController] Error inserting new heating job: ' + e.message)
        except:
            err_msg = traceback.format_exc(limit=3)
            self.logger.error('[HelheimrController] Unexpecet error inserting new heating job:\n' + err_msg)
        finally:
            self.condition_var.release()
        return ret_val


    def _scheduling_loop(self):
        self.condition_var.acquire()
        while self.run_loop:
            # Query temperature
            self.temperature_readings.append(self.query_temperature_for_heating())
            print('TODO ', self.temperature_readings)

            # Filter finished one-time jobs
            for job in [job for job in self.job_list if job.should_be_removed]:
                self._cancel_job(job)

            # Query job list for scheduled/active jobs
            runnable_jobs = (job for job in self.job_list if job.should_run)

            if len(self.job_list) == 0:
                self.logger.info('[HelheimrController] No known jobs!')
            else:
                self.logger.info('[HelheimrController] Checking job list - known jobs are:\n  * ' + \
                    '\n  * '.join([str(j) + ', runs next: {}, should run now: {}, currently running: {}'.format(
                        j.next_run, j.should_run, j.is_running) for j in self.job_list])) #TODO add time between loop iterations!

            for job in sorted(runnable_jobs):
                # If there is a job which is not running already, start it.
                if not job.is_running:
                    if isinstance(job, HeatingJob):
                        # There must only be one heating job active (but a manual request replaces an active periodic task)
                        if self.active_heating_job is None or not self.active_heating_job.is_running:
                            self.logger.info('[HelheimrController] Starting heating job "{}"'.format(job))
                            self.active_heating_job = job
                            job.start()
                        else:
                            self.logger.warning("[HelheimrController] There's already a heating job '{}' running. I'm ignoring '{}'".format(
                                self.active_heating_job, job))
                            job.skip_one_run()
                    else:
                        self.logger.info('[HelheimrController] Starting job "{}"'.format(job))
                        job.start()

            
            poll_interval = self.poll_interval if not self.job_list else min(self.poll_interval, self.idle_time)
            self.logger.info('[HelheimrController] Going to sleep for {:.1f} seconds\n'.format(max(1,poll_interval)))
            # print('Going to sleep for {:.1f} sec'.format(poll_interval))
            ret = self.condition_var.wait(timeout=max(1,poll_interval))
            #TODO maybe remove output
            # if ret:
            #     self.logger.info('[HelheimrController] Woke up due to notification!')
        
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
        job_cfg = hu.load_configuration(self.filename_job_list)
        for j in job_cfg[type(self).JOB_LIST_CONFIG_KEY_PERIODIC_HEATING]:
            job = PeriodicHeatingJob.from_libconf(j, self)
            self._add_periodic_heating_job_object(job)


    def serialize_jobs(self):
        self.condition_var.acquire()
        # Each job class (e.g. periodic heating) has a separate group within the configuration file:
        # Periodic heating jobs:
        phjs = [j for j in self.job_list if isinstance(j, PeriodicHeatingJob)]
        # Sort them by at_time:
        phds = [j.to_dict() for j in sorted(phjs, key=lambda j: j.at_time)] 
        self.condition_var.release()
        #TODO add other tasks (such as periodic display update) too!
        try:
            lcdict = {
                    type(self).JOB_LIST_CONFIG_KEY_PERIODIC_HEATING : tuple(phds)
                }
            with open(self.filename_job_list, 'w') as f:
                libconf.dump(lcdict, f)
        except:
            err_msg = traceback.format_exc(limit=3)
            self.logger.error('[HelheimrController] Error while serializing:\n' + err_msg)
            self.broadcast_error('Konnte Aufgabenliste nicht speichern:\n' + err_msg)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
    
    controller = HelheimrController()
    try:
        controller.join()
    except KeyboardInterrupt:
        controller.stop()