# The heart of my home automation project

import threading
import logging
import datetime
import time

import helheimr_utils as hu

class ManualHeatingJob(hu.Job):
    def __init__(self, controller=None):
        super(ManualHeatingJob, self).__init__(interval=24)
        self.unit = 'hours'
        self.controller = controller
        self.do(self.heat_up)
        #self.next_run = hu.datetime_now() #next_run is used to sleep in the event loop, don't modify it :-p
        self.start()
        print('Will start heating at: (DUMMY TIME!)', self.next_run) #TODO self.next_run is used for the event loop!

    def __str__(self):
        return "ManualHeatingJob()"

    def heat_up(self):
        i = 0
        while self.keep_running:
            print('I am heating')
            time.sleep(1)
            i += 1
            if i > 4:
                break
        print('Terminating HEATER!')
        controller.cancel_job(self)


def dummy_job(param):
    logging.getLogger().info('Job is running every {} sec'.format(param))

class HelheimrController:
    def __init__(self, config):
        self.lock = threading.Lock()
        self.condition_var = threading.Condition(self.lock)
        self.logger = logging.getLogger()
        self.run_loop = True
        self.job_list = list()

        self.poll_interval = 30 #TODO config

        self.worker_thread = threading.Thread(target=self.control_loop)
        self.worker_thread.start()

        self.condition_var.acquire()
        # self.job_list.append(hu.Job.every(5).seconds.do(dummy_job, 5))
        self.job_list.append(hu.Job.every(10).seconds.do(dummy_job, 10))
        # self.job_list.append(hu.Job.every().minute.do(self.stop))
        self.job_list.append(ManualHeatingJob(controller=self))
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
        unow=hu.datetime_now()
        for job in self.job_list:
            print(' foo: ', job.next_run, hu.datetime_difference(unow, job.next_run).total_seconds(), job)
        return min(self.job_list).next_run


    @property
    def idle_time(self):
        return hu.datetime_difference(hu.datetime_now(), self.next_run).total_seconds()

    # def schedule_heating(self, interval)


    def cancel_job(self, job):
        # Delete a registered job
        try:
            self.logger.info('[HelheimrController] Removing job "{}"'.format(job))
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
                    job.start()
                #TODO check if heating job is still running before invoking another!
        
            poll_interval = self.poll_interval if not self.job_list else min(self.poll_interval, self.idle_time)
            self.logger.info('[HelheimrController] Next iteration, wait for {}'.format(poll_interval))
            # self.condition_var.wait(timeout=poll_interval)#FIXME
            self.condition_var.wait(timeout=3)
            self.condition_var.release()
        self.logger.info('[HelheimrController] Shutting down control loop, terminating active tasks')
        for job in self.job_list:
            if job.is_running:
                job.stop()
        self.logger.info('[HelheimrController] Clean up done, goodbye!')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, #logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')
        
    ctrl_cfg = hu.load_configuration('configs/ctrl.cfg')

    controller = HelheimrController(ctrl_cfg)
    controller.join()