"""
Taken from github.com/dbader/schedule but adapted to UTC/timezone aware scheduling.
Extended by a scheduable heating job.
"""
try:
    from collections.abc import Hashable
except ImportError:
    from collections import Hashable
import datetime
import functools
import logging
import random
import re
import sys
import threading
import time
import traceback

from . import broadcasting
from . import common
from . import time_utils
from . import heating

logger = logging.getLogger('schedule')


class ScheduleError(Exception):
    """Base schedule exception"""
    pass


class ScheduleValueError(ScheduleError):
    """Base schedule value error"""
    pass


class IntervalError(ScheduleValueError):
    """An improper interval was used"""
    pass


class CancelJob(object):
    """
    Can be returned from a job to unschedule itself.
    """
    pass


class Scheduler(object):
    """
    Objects instantiated by the :class:`Scheduler <Scheduler>` are
    factories to create jobs, keep record of scheduled jobs and
    handle their execution.
    """
    def __init__(self):
        self.jobs = []

    def run_pending(self):
        """
        Run all jobs that are scheduled to run.

        Please note that it is *intended behavior that run_pending()
        does not run missed jobs*. For example, if you've registered a job
        that should run every minute and you only call run_pending()
        in one hour increments then your job won't be run 60 times in
        between but only once.
        """
        runnable_jobs = (job for job in self.jobs if job.should_run)
        for job in sorted(runnable_jobs):
            self._run_job(job)

    def run_all(self, delay_seconds=0):
        """
        Run all jobs regardless if they are scheduled to run or not.

        A delay of `delay` seconds is added between each job. This helps
        distribute system load generated by the jobs more evenly
        over time.

        :param delay_seconds: A delay added between every executed job
        """
        logger.info('Running *all* %i jobs with %is delay inbetween',
                    len(self.jobs), delay_seconds)
        for job in self.jobs[:]:
            self._run_job(job)
            time.sleep(delay_seconds)

    def clear(self, tag=None):
        """
        Deletes scheduled jobs marked with the given tag, or all jobs
        if tag is omitted.

        :param tag: An identifier used to identify a subset of
                    jobs to delete
        """
        if tag is None:
            del self.jobs[:]
        else:
            self.jobs[:] = (job for job in self.jobs if tag not in job.tags)

    def cancel_job(self, job):
        """
        Delete a scheduled job.

        :param job: The job to be unscheduled
        """
        try:
            self.jobs.remove(job)
        except ValueError:
            pass

    def every(self, interval=1):
        """
        Schedule a new periodic job.

        :param interval: A quantity of a certain time unit
        :return: An unconfigured :class:`Job <Job>`
        """
        job = Job(interval, self)
        return job

    def _run_job(self, job):
        ret = job.run()
        if isinstance(ret, CancelJob) or ret is CancelJob:
            self.cancel_job(job)

    @property
    def next_run(self):
        """
        Datetime when the next job should run.

        :return: A :class:`~datetime.datetime` object
        """
        if not self.jobs:
            return None
        return min(self.jobs).next_run

    # may cause an exception if next_run is None
    # @property
    # def idle_seconds(self):
    #     """
    #     :return: Number of seconds until
    #              :meth:`next_run <Scheduler.next_run>`.
    #     """
        
    #     return (self.next_run - time_utils.dt_now()).total_seconds()


class Job(object):
    """
    A periodic job as used by :class:`Scheduler`.

    :param interval: A quantity of a certain time unit
    :param scheduler: The :class:`Scheduler <Scheduler>` instance that
                      this job will register itself with once it has
                      been fully configured in :meth:`Job.do()`.

    Every job runs at a given fixed time interval that is defined by:

    * a :meth:`time unit <Job.second>`
    * a quantity of `time units` defined by `interval`

    A job is usually created and returned by :meth:`Scheduler.every`
    method, which also defines its `interval`.
    """
    def __init__(self, interval, scheduler=None):
        self.interval = interval  # pause interval * unit between runs
        self.latest = None  # upper limit to the interval
        self.job_func = None  # the job job_func to run
        self.unit = None  # time units, e.g. 'minutes', 'hours', ...
        self.at_time = None  # optional time at which this job runs
        self.last_run = None  # datetime of the last run
        self.next_run = None  # datetime of the next run
        self.period = None  # timedelta between runs, only valid for
        self.start_day = None  # Specific day of the week to start on
        self.tags = set()  # unique set of tags for the job
        self.scheduler = scheduler  # scheduler to register with

    def __lt__(self, other):
        """
        PeriodicJobs are sortable based on the scheduled time they
        run next.
        """
        return self.next_run < other.next_run

    def __str__(self):
        return (
            "Job(interval={}, "
            "unit={}, "
            "do={}, "
            "args={}, "
            "kwargs={})"
        ).format(self.interval,
                 self.unit,
                 self.job_func.__name__,
                 self.job_func.args,
                 self.job_func.keywords)

    def __repr__(self):
        def format_time(t):
            # return t.strftime('%Y-%m-%d %H:%M:%S') if t else '[never]'
            return time_utils.format(t) if t else '[never]'

        def is_repr(j):
            return not isinstance(j, Job)

        timestats = '(last run: %s, next run: %s)' % (
                    format_time(self.last_run), format_time(self.next_run))

        if hasattr(self.job_func, '__name__'):
            job_func_name = self.job_func.__name__
        else:
            job_func_name = repr(self.job_func)
        args = [repr(x) if is_repr(x) else str(x) for x in self.job_func.args]
        kwargs = ['%s=%s' % (k, repr(v))
                  for k, v in self.job_func.keywords.items()]
        call_repr = job_func_name + '(' + ', '.join(args + kwargs) + ')'

        if self.at_time is not None:
            return 'Every %s %s at %s do %s %s' % (
                   self.interval,
                   self.unit[:-1] if self.interval == 1 else self.unit,
                   self.at_time, call_repr, timestats)
        else:
            fmt = (
                'Every %(interval)s ' +
                ('to %(latest)s ' if self.latest is not None else '') +
                '%(unit)s do %(call_repr)s %(timestats)s'
            )

            return fmt % dict(
                interval=self.interval,
                latest=self.latest,
                unit=(self.unit[:-1] if self.interval == 1 else self.unit),
                call_repr=call_repr,
                timestats=timestats
            )

    @property
    def second(self):
        if self.interval != 1:
            raise IntervalError('Use seconds instead of second')
        return self.seconds

    @property
    def seconds(self):
        self.unit = 'seconds'
        return self

    @property
    def minute(self):
        if self.interval != 1:
            raise IntervalError('Use minutes instead of minute')
        return self.minutes

    @property
    def minutes(self):
        self.unit = 'minutes'
        return self

    @property
    def hour(self):
        if self.interval != 1:
            raise IntervalError('Use hours instead of hour')
        return self.hours

    @property
    def hours(self):
        self.unit = 'hours'
        return self

    @property
    def day(self):
        if self.interval != 1:
            raise IntervalError('Use days instead of day')
        return self.days

    @property
    def days(self):
        self.unit = 'days'
        return self

    @property
    def week(self):
        if self.interval != 1:
            raise IntervalError('Use weeks instead of week')
        return self.weeks

    @property
    def weeks(self):
        self.unit = 'weeks'
        return self

    @property
    def monday(self):
        if self.interval != 1:
            raise IntervalError('Use mondays instead of monday')
        self.start_day = 'monday'
        return self.weeks

    @property
    def tuesday(self):
        if self.interval != 1:
            raise IntervalError('Use tuesdays instead of tuesday')
        self.start_day = 'tuesday'
        return self.weeks

    @property
    def wednesday(self):
        if self.interval != 1:
            raise IntervalError('Use wednesdays instead of wednesday')
        self.start_day = 'wednesday'
        return self.weeks

    @property
    def thursday(self):
        if self.interval != 1:
            raise IntervalError('Use thursdays instead of thursday')
        self.start_day = 'thursday'
        return self.weeks

    @property
    def friday(self):
        if self.interval != 1:
            raise IntervalError('Use fridays instead of friday')
        self.start_day = 'friday'
        return self.weeks

    @property
    def saturday(self):
        if self.interval != 1:
            raise IntervalError('Use saturdays instead of saturday')
        self.start_day = 'saturday'
        return self.weeks

    @property
    def sunday(self):
        if self.interval != 1:
            raise IntervalError('Use sundays instead of sunday')
        self.start_day = 'sunday'
        return self.weeks

    def tag(self, *tags):
        """
        Tags the job with one or more unique indentifiers.

        Tags must be hashable. Duplicate tags are discarded.

        :param tags: A unique list of ``Hashable`` tags.
        :return: The invoked job instance
        """
        if not all(isinstance(tag, Hashable) for tag in tags):
            raise TypeError('Tags must be hashable')
        self.tags.update(tags)
        return self

    def at(self, time_str):
        """
        Specify a particular time that the job should be run at.
        The time_str has to be given in local timezone format and will be
        converted to UTC.

        :param time_str: A string in one of the following formats: `HH:MM:SS`,
            `HH:MM`,`:MM`, `:SS`. The format must make sense given how often
            the job is repeating; for example, a job that repeats every minute
            should not be given a string in the form `HH:MM:SS`. The difference
            between `:MM` and `:SS` is inferred from the selected time-unit
            (e.g. `every().hour.at(':30')` vs. `every().minute.at(':30')`).
        :return: The invoked job instance
        """
        if (self.unit not in ('days', 'hours', 'minutes')
                and not self.start_day):
            raise ScheduleValueError('Invalid unit')
        if not isinstance(time_str, str):
            raise TypeError('at() should be passed a string')
        if self.unit == 'days' or self.start_day:
            if not re.match(r'^([0-2]\d:)?[0-5]\d:[0-5]\d$', time_str):
                raise ScheduleValueError('Invalid time format')
        if self.unit == 'hours':
            if not re.match(r'^([0-5]\d)?:[0-5]\d$', time_str):
                raise ScheduleValueError(('Invalid time format for'
                                          ' an hourly job'))
        if self.unit == 'minutes':
            if not re.match(r'^:[0-5]\d$', time_str):
                raise ScheduleValueError(('Invalid time format for'
                                          ' a minutely job'))
        time_values = time_str.split(':')
        if len(time_values) == 3:
            hour, minute, second = time_values
        elif len(time_values) == 2:
            hour, minute, second = 0, 0, 0
            if self.unit == 'days':
                hour, minute = time_values
            elif self.unit == 'hours':
                minute, second = time_values
            else:
                _, second = time_values
        elif len(time_values) == 1:
            hour, minute, second = 0, 0, 0
            if self.unit == 'days':
                hour = time_values[0]
            elif self.unit == 'hours':
                minute = time_values[0]
            else:
                second = time_values[0]
        else:
            raise ScheduleValueError('Invalid time format')
        

        if self.unit == 'days' or self.start_day:
            hour = int(hour)
            if not (0 <= hour <= 23):
                raise ScheduleValueError('Invalid number of hours')
        elif self.unit == 'hours':
            hour = 0
        elif self.unit == 'minutes':
            hour = 0
            minute = 0
        minute = int(minute)
        second = int(second)
        self.at_time = time_utils.local_time_as_utc(hour, minute, second)
        return self

    def to(self, latest):
        """
        Schedule the job to run at an irregular (randomized) interval.

        The job's interval will randomly vary from the value given
        to  `every` to `latest`. The range defined is inclusive on
        both ends. For example, `every(A).to(B).seconds` executes
        the job function every N seconds such that A <= N <= B.

        :param latest: Maximum interval between randomized job runs
        :return: The invoked job instance
        """
        self.latest = latest
        return self

    def do(self, job_func, *args, **kwargs):
        """
        Specifies the job_func that should be called every time the
        job runs.

        Any additional arguments are passed on to job_func when
        the job runs.

        :param job_func: The function to be scheduled
        :return: The invoked job instance
        """
        self.job_func = functools.partial(job_func, *args, **kwargs)
        try:
            functools.update_wrapper(self.job_func, job_func)
        except AttributeError:
            # job_funcs already wrapped by functools.partial won't have
            # __name__, __module__ or __doc__ and the update_wrapper()
            # call will fail.
            pass
        self._schedule_next_run()
        # Note, we always keep self.scheduler = None since HelheimrScheduler takes
        # care of which jobs should be added to the job list
        if self.scheduler is not None:
            self.scheduler.jobs.append(self)
        return self

    @property
    def should_run(self):
        """
        :return: ``True`` if the job should be run now.
        """
        return time_utils.dt_now() >= self.next_run

    def run(self):
        """
        Run the job and immediately reschedule it.

        :return: The return value returned by the `job_func`
        """
        logger.info('Running job %s', self)
        ret = self.job_func()
        self.last_run = time_utils.dt_now()
        self._schedule_next_run()
        return ret

    def _schedule_next_run(self):
        """
        Compute the instant when this job should run next.
        """
        if self.unit not in ('seconds', 'minutes', 'hours', 'days', 'weeks'):
            raise ScheduleValueError('Invalid unit')

        if self.latest is not None:
            if not (self.latest >= self.interval):
                raise ScheduleError('`latest` is greater than `interval`')
            interval = random.randint(self.interval, self.latest)
        else:
            interval = self.interval

        self.period = datetime.timedelta(**{self.unit: interval})
        self.next_run = time_utils.dt_now() + self.period
        if self.start_day is not None:
            if self.unit != 'weeks':
                raise ScheduleValueError('`unit` should be \'weeks\'')
            weekdays = (
                'monday',
                'tuesday',
                'wednesday',
                'thursday',
                'friday',
                'saturday',
                'sunday'
            )
            if self.start_day not in weekdays:
                raise ScheduleValueError('Invalid start day')
            weekday = weekdays.index(self.start_day)
            days_ahead = weekday - self.next_run.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            self.next_run += datetime.timedelta(days_ahead) - self.period
        if self.at_time is not None:
            if (self.unit not in ('days', 'hours', 'minutes')
                    and self.start_day is None):
                raise ScheduleValueError(('Invalid unit without'
                                          ' specifying start day'))
            kwargs = {
                'second': self.at_time.second,
                'microsecond': 0
            }
            if self.unit == 'days' or self.start_day is not None:
                kwargs['hour'] = self.at_time.hour
            if self.unit in ['days', 'hours'] or self.start_day is not None:
                kwargs['minute'] = self.at_time.minute
            self.next_run = self.next_run.replace(**kwargs)
            # If we are running for the first time, make sure we run
            # at the specified time *today* (or *this hour*) as well
            if not self.last_run:
                now = time_utils.dt_now()
                if (self.unit == 'days' and self.at_time > now.timetz() and
                        self.interval == 1):
                    self.next_run = self.next_run - datetime.timedelta(days=1)
                elif self.unit == 'hours' \
                        and self.at_time.minute > now.minute \
                        or (self.at_time.minute == now.minute
                            and self.at_time.second > now.second):
                    self.next_run = self.next_run - datetime.timedelta(hours=1)
                elif self.unit == 'minutes' \
                        and self.at_time.second > now.second:
                    self.next_run = self.next_run - \
                                    datetime.timedelta(minutes=1)
        if self.start_day is not None and self.at_time is not None:
            # Let's see if we will still make that time we specified today
            if (self.next_run - time_utils.dt_now()).days >= 7:
                self.next_run -= self.period


class PeriodicHeatingJob(Job):
    @staticmethod
    def every(interval=1):
        return PeriodicHeatingJob(interval=interval)


    def __init__(self, interval):
        super(PeriodicHeatingJob, self).__init__(interval, scheduler=None)
        self.created_by = None # User name of task creator
        self.target_temperature = None # Try to reach this temperature +/- temperature_hysteresis (if set)
        self.temperature_hysteresis = None
        self.heating_duration = None # Stop heating after datetime.timedelta
        

    def do_heat_up(self, created_by, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None):
        """Call this method to schedule this heating task."""
        # Reuse sanity checks from heating class:
        sane, txt = heating.Heating.sanity_check(heating.HeatingRequest.SCHEDULED, 
            target_temperature, temperature_hysteresis, heating_duration)
        if not sane:
            raise ValueError(txt)
        
        self.target_temperature = target_temperature
        self.temperature_hysteresis = temperature_hysteresis
        self.heating_duration = heating_duration
        self.created_by = created_by
        return self.do(self.__trigger_heating)


    def __str__(self):
        txt_interval = 'every {}{}{}'.format(
            self.interval if self.interval > 1 else '',
            self.unit[:-1] if self.interval == 1 else self.unit,
            '' if self.at_time is None else ' at {}'.format(time_utils.time_as_local(self.at_time)))
        
        return '{:s} for{:s}, {:s}, created by {:s}, next run: {:s}'.format(
            'always on' if not self.target_temperature else '{:.1f}+/-{:.2f}°C'.format(
                self.target_temperature, self.temperature_hysteresis),
            'ever' if not self.heating_duration else ' {}'.format(self.heating_duration),
            txt_interval,
            self.created_by,
            time_utils.format(self.next_run))


    def __trigger_heating(self):
        heating.Heating.instance().start_heating(
            heating.HeatingRequest.SCHEDULED,
            self.created_by,
            target_temperature = self.target_temperature,
            temperature_hysteresis = self.temperature_hysteresis,
            duration = self.heating_duration
        )


    def overlaps(self, other):
        # Periodic heating jobs are (currently) assumed to run each day at a specific time
        #TODO once we start fancy heating schedules, we need to adjust this!
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
            'day_interval': self.interval,
            'at': time_utils.time_as_local(self.at_time).strftime('%H:%M:%S'), # Store as local time
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
    def from_libconf(cfg):
        day_interval = cfg['day_interval']
        # Not that he configuration file uses localtime! This time representation will be converted to proper UTC time by the Job class
        at = cfg['at']
        
        # Parse duration string (using strptime doesn't work if duration > 24h)
        d = cfg['duration'].split(':')
        hours = int(d[0])
        minutes = 0 if len(d) == 1 else int(d[1])
        seconds = 0 if len(d) == 2 else int(d[2])
        duration = datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)
        
        temperature = common.cfg_val_or_none(cfg, 'temperature')
        hysteresis = common.cfg_val_or_none(cfg, 'hysteresis')
        created_by = common.cfg_val_or_default(cfg, 'created_by', 'System')
        
        job = PeriodicHeatingJob.every(day_interval).days.at(at).do_heat_up(
                created_by,
                target_temperature=temperature, temperature_hysteresis=hysteresis, 
                heating_duration=duration)
        return job



class NonHeatingJob(Job):
    """Used to distinguish PeriodicHeatingJobs from NonHeatingJobs (from generic Jobs that
    someone just added into the scheduling list, without us knowing...)"""
    def __init__(self, interval, function_name):
        super(NonHeatingJob, self).__init__(interval)
        self.function_name = function_name


    def to_dict(self):
        """Return a dict for serialization via libconf."""
        d = {
            'interval': self.interval,
            'unit': self.unit
        }
        if self.at_time is not None:
            fmt_str = '%H:%M:%S'
            if self.unit == 'hours':
                fmt_str = '%M:%S'
            elif self.unit == 'minutes':
                fmt_str = '%S'
            d['at'] = time_utils.time_as_local(self.at_time).strftime(fmt_str)
        return d


    @staticmethod
    def from_libconf(cfg):
        job_type = common.cfg_val_or_none(cfg, 'type')
        if job_type is None:
            raise ValueError("Non-heating job is missing 'type = ...' Check the configuration file.")

        # Use the configured name as function name to execute:
        this_module = sys.modules[__name__]
        target_function = getattr(this_module, job_type)

        interval = int(common.cfg_val_or_default(cfg, 'interval', 1))
        unit = common.cfg_val_or_none(cfg, 'unit')
        job = NonHeatingJob(interval, job_type)
        if unit == 'seconds' or (unit == 'second' and interval == 1):
            job = job.seconds
        elif unit == 'minutes' or (unit == 'minute' and interval == 1):
            job = job.minutes
        elif unit == 'hours' or (unit == 'hour' and interval == 1):
            job = job.hours
        elif unit == 'days' or (unit == 'day' and interval == 1):
            job = job.days
        elif unit == 'weeks' or (unit == 'week' and interval == 1):
            job = job.days
        else:
            raise ScheduleValueError("Invalid unit '{}' or unit/interval combination with interval '{}'".format(unit, interval))
        
        at = common.cfg_val_or_none(cfg, 'at')
        if at is not None:
            job = job.at(at)

        return job.do(target_function)



def broadcast_dummy_message():
    logging.getLogger().info('Periodic dummy task reporting for duty.')
    broadcasting.MessageBroadcaster.instance().info('Periodic dummy task reporting for duty.')



class HelheimrScheduler(Scheduler):
    # libconfig++ key to look up scheduled heating jobs
    JOB_LIST_CONFIG_KEY_PERIODIC_HEATING = 'heating_jobs'

    # ... and similarly, for non-heating jobs
    JOB_LIST_CONFIG_KEY_PERIODIC_NON_HEATING = 'non_heating_jobs'

    __instance = None

    @staticmethod
    def instance():
        """Returns the singleton."""
        return HelheimrScheduler.__instance


    @staticmethod
    def init_instance(ctrl_config, job_list_filename):
        """
        Initialize the singleton.

        :param ctrl_config:       libconfig++ system configuration
        :param job_list_filename: filename where to load/store our jobs
        """
        if HelheimrScheduler.__instance is None:
            HelheimrScheduler(ctrl_config, job_list_filename)
        return HelheimrScheduler.__instance

    
    def __init__(self, ctrl_cfg, job_list_filename):
        """Virtually private constructor, use HelheimrScheduler.init_instance() instead."""
        if HelheimrScheduler.__instance is not None:
            raise RuntimeError("HelheimrScheduler is a singleton!")
        HelheimrScheduler.__instance = self

        super(HelheimrScheduler,self).__init__()

        # We use a condition variable to sleep during scheduled tasks (in case we need to wake up earlier)
        self._lock = threading.Lock()
        self._condition_var = threading.Condition(self._lock)

        self._run_loop = True # Flag to abort the scheduling/main loop

        self._poll_interval = ctrl_cfg['scheduler']['idle_time']

        self._job_list_filename = job_list_filename # Filename to load/store the scheduled jobs

        # The actual scheduling runs in a separate thread
        self._worker_thread = threading.Thread(target=self.__scheduling_loop) 
        self._worker_thread.start()

        # Load existing jobs:
        job_config = common.load_configuration(self._job_list_filename)
        self.deserialize_jobs(job_config)


    @property
    def idle_time(self):
        """:return: Idle time in seconds before the next (scheduled) job is to be run."""
        next_time = self.next_run
        now = time_utils.dt_now()
        if next_time is not None and next_time >= now:
            return (next_time - now).total_seconds()
        return self._poll_interval

   
    def shutdown(self):
        logging.getLogger().info('[HelheimrScheduler] Preparing shutdown.')
        self._condition_var.acquire()
        self._run_loop = False
        self._condition_var.notify()  # Wake up controller/scheduler
        self._condition_var.release()
        self._worker_thread.join()
        logging.getLogger().info('[HelheimrScheduler] Scheduler has been shut down.')



    def schedule_heating_job(self, created_by, target_temperature=None, temperature_hysteresis=0.5, heating_duration=None,
            day_interval=1, at_hour=6, at_minute=0, at_second=0):
        job = PeriodicHeatingJob.every(day_interval).days.at(
                '{:02d}:{:02d}:{:02d}'.format(at_hour, at_minute, at_second)).do_heat_up(
                created_by,
                target_temperature=target_temperature, temperature_hysteresis=temperature_hysteresis, 
                heating_duration=heating_duration)
        ret = self.__schedule_heating_job(job)
        if ret:
            self.serialize_jobs()
        return ret


    def __schedule_heating_job(self, periodic_heating_job):
        ret_val = False
        msg = ''
        self._condition_var.acquire()
        if any([j.overlaps(periodic_heating_job) for j in self.jobs]):
            msg = 'The requested periodic job "{}" overlaps with an existing one!'.format(periodic_heating_job)
        else:
            self.jobs.append(periodic_heating_job)
            self._condition_var.notify()
            ret_val = True
        if not ret_val:
            logging.getLogger().error('[HelheimrController] Error inserting new heating job: ' + msg)
        self._condition_var.release()
        return ret_val


    def __scheduling_loop(self):
        self._condition_var.acquire()
        while self._run_loop:
            #TODO remove
            print('TODO REMOVE JOB LIST DEBUG::::::::::::::::::::::::::::::')
            for job in self.jobs:
                print(job, time_utils.format(job.next_run))

            self.run_pending()
          
            # print('TODO REMOVE IDLE_TIME: {}'.format(datetime.timedelta(seconds=self.idle_time)))
            poll_interval = max(1, self._poll_interval if len(self.jobs) == 0 else min(self._poll_interval, self.idle_time))
            logging.getLogger().info('[HelheimrScheduler] Going to sleep for {:.1f} seconds\n'.format(poll_interval))
            
            # Go to sleep
            self._condition_var.wait(timeout = poll_interval)
        self._condition_var.release()


    def deserialize_jobs(self, jobs_config):
        if jobs_config is None:
            return

        heating_jobs = jobs_config[type(self).JOB_LIST_CONFIG_KEY_PERIODIC_HEATING]
        if heating_jobs is not None:
            for j in heating_jobs:
                try:
                    job = PeriodicHeatingJob.from_libconf(j)
                    self.__schedule_heating_job(job)
                except:
                    err_msg = traceback.format_exc(limit=3)
                    logging.getLogger().error('[HelheimrScheduler] Error while loading heating jobs:\n' + err_msg)

        non_heating_jobs = jobs_config[type(self).JOB_LIST_CONFIG_KEY_PERIODIC_NON_HEATING]
        if non_heating_jobs is not None:
            for j in non_heating_jobs:
                self._condition_var.acquire()
                try:
                    job = NonHeatingJob.from_libconf(j)
                    self.jobs.append(job)
                except:
                    err_msg = traceback.format_exc(limit=3)
                    logging.getLogger().error('[HelheimrScheduler] Error while loading non-heating jobs:\n' + err_msg)
                finally:
                    self._condition_var.notify()
                    self._condition_var.release()
        

    def serialize_jobs(self):
        self._condition_var.acquire()
        # Each job class (e.g. periodic heating) has a separate group within the configuration file:
        # Periodic heating jobs:
        phjs = [j for j in self.jobs if isinstance(j, PeriodicHeatingJob)]
        # Sort them by at_time:
        phds = [j.to_dict() for j in sorted(phjs, key=lambda j: j.at_time)]
        # Periodic non-heating jobs:
        pnhjs = [j.to_dict() for j in self.jobs if isinstance(j, NonHeatingJob)]
        self._condition_var.release()
        
        try:
            lcdict = {
                    type(self).JOB_LIST_CONFIG_KEY_PERIODIC_HEATING : tuple(phds),
                    type(self).JOB_LIST_CONFIG_KEY_PERIODIC_NON_HEATING : tuple(pnhjs)
                }
            with open(self._job_list_filename, 'w') as f:
                libconf.dump(lcdict, f)
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error('[HelheimrController] Error while serializing:\n' + err_msg)

