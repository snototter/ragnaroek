# The heart of my home automation project

import threading
import logging
import datetime
import time

import helheimr_utils as hu

class HeatingJob(hu.Job):
    def __init__(self, interval, controller, target_temperature=None, temperature_hysteresis=None, duration=None):
        super(HeatingJob, self).__init__(interval)
        self.controller = controller                    #TODO remove# Store to cancel or report errors
        self.target_temperature = target_temperature    # Try to reach this temperature +/- temperature_hysteresis (if set)
        self.temperature_hysteresis = temperature_hysteresis
        self.heating_duration = duration                # Stop heating after datetime.duration
    
    def __str__(self):
        return '{:s} for{:s}'.format('always on' if not self.target_temperature else '{:.1f}+/-{:.2f}°C'.format(self.target_temperature, self.temperature_hysteresis),
            'ever' if not self.heating_duration else ' {}'.format(self.heating_duration))

#TODO periodicHeatingJob
class PeriodicHeatingJob(HeatingJob):
    pass 

class ManualHeatingJob(HeatingJob):
    def __init__(self, controller, target_temperature=None, temperature_hysteresis=None, duration=None):
        # Set a dummy interval of 24 hours (we will start the task immediately)
        super(ManualHeatingJob, self).__init__(24, controller, 
            target_temperature, temperature_hysteresis, duration)
        self.unit = 'hours'
        self.do(self.heat_up)
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
    def should_run(self):
        # Only start once!
        return True and not self.was_started

    def heat_up(self):
        self.was_started = True
        start_time = hu.datetime_now()
        if self.heating_duration is not None:
            end_time = start_time + self.heating_duration
        else:
            end_time = None

        while self.keep_running:
            #TODO use controller
            print('I am heating for {} now'.format(hu.datetime_difference(start_time, hu.datetime_now())))
            if end_time is not None and hu.datetime_now() >= end_time:
                break
            time.sleep(1)
        self.keep_running = False
        self.controller.cancel_job(self)
        logging.getLogger().info('[ManualHeatingJob] Terminating "{}" after {}'.format(self, hu.datetime_difference(start_time, hu.datetime_now())))


# def dummy_job(param):
#     logging.getLogger().info('Job is running every {} sec'.format(param))

class HelheimrController:
    def __init__(self, config):
        self.lock = threading.Lock()
        self.condition_var = threading.Condition(self.lock)
        self.logger = logging.getLogger()
        self.run_loop = True
        self.job_list = list()

        self.poll_interval = 30 #TODO config
        self.active_heating_job = None

        self.worker_thread = threading.Thread(target=self.control_loop)
        self.worker_thread.start()

        self.condition_var.acquire()
        # self.job_list.append(hu.Job.every(5).seconds.do(dummy_job, 5))
        # self.job_list.append(hu.Job.every(10).seconds.do(dummy_job, 10))
        # self.job_list.append(hu.Job.every().minute.do(self.stop))
        self.job_list.append(ManualHeatingJob(controller=self, target_temperature=None, 
            temperature_hysteresis=None, duration=datetime.timedelta(seconds=10)))
        self.job_list.append(ManualHeatingJob(controller=self, target_temperature=23, 
            temperature_hysteresis=0.5))
        self.job_list.append(hu.Job.every(15).seconds.do(self.stop))
        self.condition_var.notify()
        self.condition_var.release()

        #TODO keep active heating job as separate variable


    def stop(self):
        self.run_loop = False


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


    def turn_on_manually(self, duration=None):
        self.condition_var.acquire()
        self.condition_var.release()
        # self.lock.acquire()
        # self.lock.release()
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
    


    def control_loop(self):
        while self.run_loop:
            self.condition_var.acquire()
            # Query job list for scheduled/active jobs
            runnable_jobs = (job for job in self.job_list if job.should_run)
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
                    print('Job {} will be run_next on {}'.format(job, hu.datetime_as_local(job.next_run)))

                #TODO check if heating job is still running before invoking another!
            
            # heating_jobs = (job for job in self.job_list if isinstance(job, HeatingJob))
        
            poll_interval = self.poll_interval if not self.job_list else min(self.poll_interval, self.idle_time)
            # self.logger.info('[HelheimrController] Next iteration, wait for {}'.format(poll_interval))
            self.condition_var.wait(timeout=poll_interval)
            self.condition_var.release()

        self.logger.info('[HelheimrController] Shutting down control loop, terminating active jobs')
        for job in self.job_list:
            if job.is_running:
                self.logger.info('[HelheimrController] Terminating "{}"'.format(job))
                job.stop()
        self.logger.info('[HelheimrController] Clean up done, goodbye!')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        
    ctrl_cfg = hu.load_configuration('configs/ctrl.cfg')

    controller = HelheimrController(ctrl_cfg)
    controller.join()
    #TODO shut down heating