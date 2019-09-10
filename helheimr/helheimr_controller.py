# The heart of my home automation project

import threading
import logging
import datetime
import time

import helheimr_utils as hu
import helheimr_bot as hb
import helheimr_raspbee as hr
import helheimr_weather as hw

def to_duration(hours, minutes, seconds=0):
    return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)

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
                # current_temperature = ...
                # bang_bang.update(current_temperature)
                pass
            else:
                should_heat = True
            # TODO ensure that heating is running

            print('I am heating for {} now'.format(hu.datetime_difference(start_time, hu.datetime_now())))
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
        return "PeriodicHeatingJob: every {} {}{}, {}".format(self.interval,
                 self.unit[-1] if self.interval == 1 else self.unit,
                 '' if self.at_time is None else ' at {}'.format(self.at_time),
                 super(PeriodicHeatingJob, self).__str__())

    def overlaps(self, other):
        # Periodic heating jobs are (currently) assumed to run each day at a specific time
        start_this = datetime.datetime.combine(datetime.datetime.today(), self.at_time)
        end_this = start_this + self.heating_duration
        start_other = datetime.datetime.combine(datetime.datetime.today(), other.at_time)
        end_other = start_other + other.heating_duration
        print('comparing', start_this, end_this, ' vs ', start_other, end_other)
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
    def __init__(self, config, raspbee_wrapper, telegram_bot):
        self.raspbee_wrapper = raspbee_wrapper # The wrapper which is actually able to turn stuff on/off
        self.telegram_bot = telegram_bot # Telegram bot for notifications and user input (on-the-go ;-)

        self.lock = threading.Lock()    # We use a condition variable to sleep during scheduled tasks (in case we need to wake up earlier)
        self.condition_var = threading.Condition(self.lock)
        self.logger = logging.getLogger()

        self.run_loop = True # Flag to abort the scheduling/main loop
        self.job_list = list() # List of scheduled/manually inserted jobs

        self.poll_interval = 30 #TODO config
        self.active_heating_job = None # References the currently active heating job (for convenience)

        self.worker_thread = threading.Thread(target=self._scheduling_loop) # The scheduler runs in a separate thread
        self.worker_thread.start()

        # # self._add_manual_heating_job(None, None, datetime.timedelta(seconds=10))
        # # self._add_manual_heating_job(23, 0.5, None)
        # try:
        #     self.job_list.append(HeatingJob.every(10).seconds.do_heat_up(target_temperature=20.0, temperature_hysteresis=0.5, heating_duration=to_duration(0, 0, 5)))
        #     self.job_list.append(HeatingJob.every(4).seconds.do_heat_up(target_temperature=20.0, temperature_hysteresis=0.5, heating_duration=to_duration(0, 0, 5)))
        # except Exception as e:
        #     print('This error was expected: ', e)
        #     pass
        self._add_periodic_heating_job(target_temperature=None, temperature_hysteresis=0.5, 
            heating_duration=datetime.timedelta(hours=2),
            day_interval=1, at_hour=6, at_minute=30)
        self._add_periodic_heating_job(target_temperature=None, temperature_hysteresis=0.5, 
            heating_duration=datetime.timedelta(hours=3),
            day_interval=1, at_hour=7, at_minute=59)

        # # self.job_list.append(hu.Job.every(5).seconds.do(dummy_job, 5))
        # # self.job_list.append(hu.Job.every(10).seconds.do(dummy_job, 10))
        # # self.job_list.append(hu.Job.every().minute.do(self.stop))
        # # self.job_list.append(ManualHeatingJob(controller=self, target_temperature=None, 
        # #     temperature_hysteresis=None, duration=datetime.timedelta(seconds=10)))
        # # self.job_list.append(ManualHeatingJob(controller=self, target_temperature=23, 
        #     # temperature_hysteresis=0.5))
        # # self.job_list.append(hu.Job.every(3).seconds.do(self.dummy_stop))
        self.condition_var.acquire()
        self.job_list.append(hu.Job.every(15).seconds.do(self.stop))
        self.job_list.append(hu.Job.every(5).seconds.start_immediately.do(self.dummy_query))
        self.condition_var.notify()
        self.condition_var.release()

    



    def dummy_query(self):
        status = self.raspbee_wrapper.query_temperature()
        txt = '*Aktuelle Temperatur:*\n' + '\n'.join(map(str, status))
        self.logger.info(txt)

    def dummy_stop(self):
        if self.active_heating_job:
            self.active_heating_job.stop_heating()


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
        self.worker_thread.join()


    @property
    def next_run(self):
        if len(self.job_list) == 0:
            return None
        return min(self.job_list).next_run


    @property
    def idle_time(self):
        return hu.datetime_difference(hu.datetime_now(), self.next_run).total_seconds()

    # def schedule_heating(self, interval)


    def cancel_job(self, job):
        # Delete a registered job
        try:
            self.logger.info('[HelheimrController] Removing job "{}"'.format(job))
            if job == self.active_heating_job:
                self.active_heating_job = None
            self.job_list.remove(job)
        except ValueError:
            self.logger.error('[HelheimrController] Could not cancel job "{}"'.format(job))


    def turn_on_manually(self, target_temperature=None, temperature_hysteresis=0.5, duration=None):
        # self.condition_var.acquire()
        # self.condition_var.release()
        #TODO abort running task
        if duration is None:
            self.logger.info('[HelheimrController] Start heating (forever) due to user request')
        else:
            if duration < 0:
                self.logger.error('[HelheimrController] Invalid duration provided, ignoring request')
                return False
            self.logger.info('[HelheimrController] Start heating for {} TODO hours?'.format(duration))
        return True


    def turn_off_manually(self):
        self.logger.info('[HelheimrController] Stop heating')
        return True

    
    def _add_manual_heating_job(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None):
        self.condition_var.acquire()
        ret = False
        if any([isinstance(job, ManualHeatingJob) for job in self.job_list]):
            self.logger.warning("[HelheimrController] There's already a ManualHeatingJob in my task list. I'm ignoring this request.")
        else:
            mhj = HeatingJob.manual(target_temperature, temperature_hysteresis, heating_duration)
            self.logger.info("[HelheimrController] Adding a ManualHeatingJob ({}) to my task list.".format(mhj))
            self.job_list.append(mhj)
            # self.job_list.append(ManualHeatingJob(controller=self, target_temperature=target_temperature, 
            #     temperature_hysteresis=temperature_hysteresis, duration=heating_duration))
            ret = True
            self.condition_var.notify()
        self.condition_var.release()
        return ret


    def _add_periodic_heating_job(self, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None,
            day_interval=1, at_hour=6, at_minute=0):
        self.condition_var.acquire()
        try: 
            #TODO check for overlapping heating jobs!
            job = HeatingJob.every(day_interval).days.at(
                '{:02d}:{:02d}:00'.format(at_hour, at_minute)).do_heat_up(
                target_temperature=target_temperature, temperature_hysteresis=temperature_hysteresis, 
                heating_duration=heating_duration)
            if any([j.overlaps(job) for j in self.job_list]):
                raise hu.ScheduleError('The requested periodic job "{}" overlaps with an existing one!'.format(job))
            self.job_list.append(job)
            self.condition_var.notify()
            #TODO print stack trace!!!!!!
        except Exception as e:
            print('\nOHOHOHOHOHOH TODO Error:\n', e)#TODO
        finally:
            self.condition_var.release()


    def _scheduling_loop(self):
        self.condition_var.acquire()
        while self.run_loop:
            # Filter finished one-time jobs
            for job in [job for job in self.job_list if job.should_be_removed]:
                self.cancel_job(job)

            # Query job list for scheduled/active jobs
            runnable_jobs = (job for job in self.job_list if job.should_run)
            print('\n\nNext loop iteration, known jobs:\n' + '\n'.join(map(str, self.job_list)))
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
                    else:
                        job.start()
                    # print('Job {} will be run_next on {}'.format(job, hu.datetime_as_local(job.next_run)))

            
            poll_interval = self.poll_interval if not self.job_list else min(self.poll_interval, self.idle_time)
            print('Going to sleep for {:.1f} sec'.format(poll_interval))
            ret = self.condition_var.wait(timeout=max(1,poll_interval))
            if ret:
                print('\n\nController woke up due to notification!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!') #TODO remove output
        
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
        
    ctrl_cfg = hu.load_configuration('configs/ctrl.cfg')
    raspbee_wrapper = hr.RaspBeeWrapper(ctrl_cfg)

    weather_cfg = hu.load_configuration('configs/owm.cfg')
    weather_forecast = hw.WeatherForecastOwm(weather_cfg)

    bot_cfg = hu.load_configuration('configs/bot.cfg')
    telegram_bot = hb.HelheimrBot(bot_cfg, raspbee_wrapper, weather_forecast) #TODO refactor to use controller instead of wrapper!

    controller = HelheimrController(ctrl_cfg, raspbee_wrapper, telegram_bot)
    try:
        telegram_bot.start()
        telegram_bot.idle()
        controller.stop()
        #controller.join()
    except KeyboardInterrupt:
        controller.stop()
    #TODO shut down heating