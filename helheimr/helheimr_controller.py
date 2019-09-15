# The heart of my home automation project

import datetime
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

def to_duration(hours, minutes, seconds=0):
    return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)


class HeatingConfigurationError(Exception):
    """Used to indicate wrong configurations (e.g. temperature/duration,...)"""
    def __init__(self, message):
        self.message = message


class HeatingJob(hu.Job):
    @staticmethod
    def every(interval=1):
        return PeriodicHeatingJob(interval=interval)
        # return hj.do(hj.heating_loop)

    @staticmethod
    def manual(target_temperature=None, temperature_hysteresis=0.5, heating_duration=None):
        mhj = ManualHeatingJob(controller=None) #, target_temperature=target_temperature, temperature_hysteresis=temperature_hysteresis, duration=heating_duration)
        return mhj.do_heat_up(target_temperature, temperature_hysteresis, heating_duration)

    def __init__(self, interval, controller=None): #, controller=None, target_temperature=None, temperature_hysteresis=None, duration=None):
        super(HeatingJob, self).__init__(interval)
        self.controller = controller #TODO needed to forward errors to the users (via telegram or display) 
        self.target_temperature = None#target_temperature    # Try to reach this temperature +/- temperature_hysteresis (if set)
        self.temperature_hysteresis = None#temperature_hysteresis
        self.heating_duration = None# = duration                # Stop heating after datetime.duration
        self.lock = threading.Lock()
        self.cv_loop_idle = threading.Condition(self.lock) # Use this condition variable instead of sleep() inside a heating job (upon stopping, self.keep_running=False, it will notify all waiting threads)

    def do_heat_up(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None):
        # Sanity checks
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
        return self.do(self.heating_loop)

    def stop(self):
        if self.keep_running:
            self.keep_running = False
            self.cv_loop_idle.acquire()
            self.cv_loop_idle.notifyAll()
            self.cv_loop_idle.release()
            self.worker_thread.join(timeout=10) #TODO timeout
    
    def __str__(self):
        return '{:s} for{:s}'.format('always on' if not self.target_temperature else '{:.1f}+/-{:.2f}°C'.format(self.target_temperature, self.temperature_hysteresis),
            'ever' if not self.heating_duration else ' {}'.format(self.heating_duration))

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
            if use_temperature_controller:
                #TODO
                # current_temperature = ...
                # bang_bang.update(current_temperature)
                pass
            else:
                should_heat = True
            # TODO ensure that heating is running

            print('{} heating {}for {} now, finish {}'.format(
                'Manual' if isinstance(self, ManualHeatingJob) else 'Periodic',
                ' to {}+/-{} °C '.format(self.target_temperature, self.temperature_hysteresis) if self.target_temperature is not None else '',
                hu.datetime_difference(start_time, hu.datetime_now()),
                end_time if end_time is not None else 'never'
                ))
            if end_time is not None and hu.datetime_now() >= end_time:
                break
            self.cv_loop_idle.wait(timeout=1)
        self.cv_loop_idle.release
        self.keep_running = False
        # self.controller.cancel_job(self)
        logging.getLogger().info('[ManualHeatingJob] Terminating "{}" after {}'.format(self, hu.datetime_difference(start_time, hu.datetime_now())))

    def stop_heating(self):
        self.keep_running = False
        self.cv_loop_idle.acquire()
        self.cv_loop_idle.notify()
        self.cv_loop_idle.release()
        self.worker_thread.join()

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


class ManualHeatingJob(HeatingJob):
    def __init__(self, controller):#, target_temperature=None, temperature_hysteresis=None, duration=None):
        # Set a dummy interval of 72 hours (we will start the task immediately)
        super(ManualHeatingJob, self).__init__(72, controller) 
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
    def __init__(self):#, config, raspbee_wrapper, telegram_bot):
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
        # # Create a dummy heating job:
        # start_time = (datetime.datetime.now() + datetime.timedelta(seconds=15)).time()
        # self._add_periodic_heating_job(27.8, 0.8, datetime.timedelta(hours=2), 1, at_hour=start_time.hour, at_minute=start_time.minute, at_second=start_time.second)

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

    
    def query_heating_state(self):
        """:return: is_heating(bool), list(PlugState)"""
        return self.raspbee_wrapper.query_heating()


    def query_temperature(self):
        """:return: list(TemperatureState)"""
        return self.raspbee_wrapper.query_temperature()


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
        msg.append('*Heizung:*')
        reachable = hu.check_url(self.known_url_raspbee)
        msg.append('\u2022 deCONZ API ist {}'.format('online' if reachable else 'offline :bangbang:'))
        if reachable:
            msg.append(self.raspbee_wrapper.query_full_state())
        
        return '\n'.join(msg)

    # def dummy_stop(self):
    #     if self.active_heating_job:
    #         self.active_heating_job.stop_heating()


    def stop(self):
        self.run_loop = False
        self.condition_var.acquire()
        self.condition_var.notify() # Wake up controller/scheduler
        self.condition_var.release()
        self.worker_thread.join()

        if self.telegram_bot:
            # TODO send shutdown message
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

#TODO for configuring from bot:
    # def schedule_heating(self, interval)


    def _cancel_job(self, job):
        # Delete a registered job - make sure to acquire the lock first!
        try:
            self.logger.info('[HelheimrController] Removing job "{}"'.format(job))
            if job == self.active_heating_job:
                self.active_heating_job = None
            self.job_list.remove(job)
        except ValueError:
            self.logger.error('[HelheimrController] Could not cancel job "{}"'.format(job))


    def turn_on_manually(self, target_temperature=None, temperature_hysteresis=0.5, duration=None):
        """TODO
        duration datetime.timedelta
        """
        try:
            self._add_manual_heating_job(target_temperature, temperature_hysteresis, duration)
            return True, 'Befehl wurde an Heizungssteuerung weitergeleitet.'
        except HeatingConfigurationError as e:
            return False, e.message
        except: # TODO custom exception (heatingconfigerror, nur e.message/text anzeigen) vs general exception
            err_msg = traceback.format_exc(limit=3)
            return False, '[Traceback]: '+err_msg # TODO traceback
        # # self.condition_var.acquire()
        # # self.condition_var.release()
        # #TODO abort running task (cancel if manual, stop this run if periodic)
        # #FIXME implement
        # if duration is None:
        #     self.logger.info('[HelheimrController] Start heating (forever) due to user request')
        # else:
        #     if duration < 0:
        #         self.logger.error('[HelheimrController] Invalid duration provided, ignoring request')
        #         return False, 'TODO'
        #     self.logger.info('[HelheimrController] Start heating for {}'.format(duration))
        # return True, 'TODO'


    def turn_off_manually(self):
        self.logger.info('[HelheimrController] Stop heating')
        return True, 'FOO TODO'

    
    def _add_manual_heating_job(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None):
        mhj = HeatingJob.manual(target_temperature, temperature_hysteresis, heating_duration)
        #TODO change: if there is an existing job, delete that and start the new one
        #TODO add param user (name) for message (terminating Job started by XY)
        self.condition_var.acquire()
        ret = False
        #TODO active heating is a separate variable - but we still need to check for heating jobs
        #e.g. start manually, what happens with a periodic job starting in 2 minutes?
        if any([isinstance(job, ManualHeatingJob) for job in self.job_list]):
            self.logger.warning("[HelheimrController] There's already a ManualHeatingJob in my task list. I'm ignoring this request.")
        else:
            
            self.logger.info("[HelheimrController] Adding a ManualHeatingJob ({}) to my task list.".format(mhj))
            self.job_list.append(mhj)
            # self.job_list.append(ManualHeatingJob(controller=self, target_temperature=target_temperature, 
            #     temperature_hysteresis=temperature_hysteresis, duration=heating_duration))
            ret = True
            self.condition_var.notify()
        self.condition_var.release()
        return ret


    def _add_periodic_heating_job(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None,
            day_interval=1, at_hour=6, at_minute=0, at_second=0):
        self.condition_var.acquire()
        try: 
            #TODO check for overlapping heating jobs!
            job = HeatingJob.every(day_interval).days.at(
                '{:02d}:{:02d}:{:02d}'.format(at_hour, at_minute, at_second)).do_heat_up(
                target_temperature=target_temperature, temperature_hysteresis=temperature_hysteresis, 
                heating_duration=heating_duration)
            if any([j.overlaps(job) for j in self.job_list]):
                raise hu.ScheduleError('The requested periodic job "{}" overlaps with an existing one!'.format(job))
            self.job_list.append(job)
            self.condition_var.notify()
            #TODO print stack trace!!!!!!
        except:
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
            print('\n\nNext loop iteration, known jobs:\n' + '\n'.join(map(str, self.job_list))) # TODO zeit zwischen aufrufen plotten!
            for job in sorted(runnable_jobs):
                # If there is a job which is not running already, start it.
                if not job.is_running:
                    self.logger.info('[HelheimrController] Starting job "{}"'.format(job))
                    if isinstance(job, HeatingJob):
                        # There must only be one heating job active!
                        #TODO but manual takes preference over scheduled
                        if self.active_heating_job is None:
                            self.active_heating_job = job
                            job.start()
                        else:
                            self.logger.warning("[HelheimrController] There's already a heating job '{}' running. I'm ignoring '{}'".format(self.active_heating_job, job))
                            #TODO implement job.skip() - calls _schedule_next()
                    else:
                        job.start()
                    # print('Job {} will be run_next on {}'.format(job, hu.datetime_as_local(job.next_run)))

            
            poll_interval = self.poll_interval if not self.job_list else min(self.poll_interval, self.idle_time)
            # print('Going to sleep for {:.1f} sec'.format(poll_interval))
            ret = self.condition_var.wait(timeout=max(1,poll_interval))
            # if ret:
            #     print('\n\nController woke up due to notification!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!') #TODO remove output
        
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


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        
    

    controller = HelheimrController()
    #ctrl_cfg, raspbee_wrapper, telegram_bot)
    #TODO telegram bot wird von controller gestartet
    #TODO weather forecast => member von controller
    #TODO controller.start
    try:
        # telegram_bot.start()
        # telegram_bot.idle()
        controller.join()
        # controller.stop()
    except KeyboardInterrupt:
        controller.stop()
    #TODO shut down heating