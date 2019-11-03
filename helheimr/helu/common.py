#!/usr/bin/python
# coding=utf-8
"""
Common utilities for timing, logging, etc.
Basically all the stuff that's too small to make up a separate module.
"""

from emoji import emojize
import libconf
#import random
import timeit
import io
import re
import sys
import subprocess
import os
import psutil
import datetime
import traceback


#######################################################################
# Utilities
def slurp_stripped_lines(filename):
    """Read the file line-by-line, return a list of the (trimmed!) lines."""
    with open(filename) as f:
        return [s.strip() for s in f.readlines()]


def tail(filename, lines=10, as_list=True):
    """efficient implementation to 'tail' a file, adapted from https://stackoverflow.com/a/136368"""
    total_lines_wanted = lines
    with open(filename, 'rb') as f:

        BLOCK_SIZE = 1024
        f.seek(0, 2)
        block_end_byte = f.tell()
        lines_to_go = total_lines_wanted
        block_number = -1
        blocks = [] # blocks of size BLOCK_SIZE, in reverse order starting
                    # from the end of the file
        while lines_to_go > 0 and block_end_byte > 0:
            if (block_end_byte - BLOCK_SIZE > 0):
                # read the last block we haven't yet read
                f.seek(block_number*BLOCK_SIZE, 2)
                blocks.append(f.read(BLOCK_SIZE))
            else:
                # file too small, start from begining
                f.seek(0,0)
                # only read what was not read
                blocks.append(f.read(block_end_byte))
            lines_found = blocks[-1].count('\n'.encode('utf-8'))
            lines_to_go -= lines_found
            block_end_byte -= BLOCK_SIZE
            block_number -= 1
        all_read_text = ''.join(reversed([b.decode('utf-8') for b in blocks]))
        if as_list:
            return all_read_text.splitlines()[-total_lines_wanted:]
        else:
            return '\n'.join(all_read_text.splitlines()[-total_lines_wanted:])
    return None


def emo(txt):
    """Simply wrapping emoji.emojize() since I often need/forget the optional parameter ;-)"""
    return emojize(txt, use_aliases=True)


def cfg_val_or_none(cfg, key):
    """Look up key in the 'cfg' dictionary. If not found, returns None."""
    return cfg[key] if key in cfg else None

        
def cfg_val_or_default(cfg, key, default):
    """Look up key in the 'cfg' dictionary. If not found, returns the 'default' value."""
    v = cfg_val_or_none(cfg, key)
    return default if v is None else v


def load_configuration(filename):
    """Loads a libconfig configuration file."""
    try:
        with open(filename) as f:
            return libconf.load(f)
    except FileNotFoundError:
        return None


def proc_info():
    """Return process id and current memory usage."""
    pid = os.getpid()
    proc = psutil.Process(pid)
    mem_bytes = proc.memory_info().rss
    mb = mem_bytes/2**20
    return (pid, mb)


def safe_shell_output(*args):
    """Executes the given shell command and returns the output
    with leading/trailing whitespace trimmed. For example:
    * sso('ls')
    * sso('ls', '-l', '-a')

    Returns the tuple (True/False, output/error_message)
    """
    try:
        # with open(os.devnull, 'wb') as devnull:
        #     by = subprocess.check_output(list(args), stderr=devnull)
        by = subprocess.check_output(list(args))
        out = by.decode('utf-8').strip()
        success = True
    except:
        out = traceback.format_exc(limit=3)
        success = False
    return success, out


def shell_whoami():
    return safe_shell_output('whoami')

def shell_pwd():
    return safe_shell_output('pwd')

def shell_uptime():
    return safe_shell_output('uptime', '-p')

def shell_service_log(num_lines):
    """Returns the last num_lines log lines of this service's log."""
    return safe_shell_output('journalctl', '-u', 'helheimr-heating.service', '--no-pager', '-n', str(num_lines))

def shell_heating_log(num_lines):
    """Returns the last num_lines logged by the heating system wrapper."""
    return safe_shell_output('/bin/bash', '-c', r"journalctl -u helheimr-heating.service --no-pager | grep '\[Heating\]' | tail -n {:d}".format(num_lines))

def shell_update_repository():
    # We set the service's working directory accordingly.
    # If you need something similar but 'cd ...' first, the
    # following also works:
    # success, txt = safe_shell_output('/bin/bash', '-c', 'cd /some/path && git status')
    # # success, txt = safe_shell_output('git', 'pull', 'origin', 'master')
    # # if success and pip_update:
    # # !! pip install would need to first source the .venv :-/
    # #     psuc, ptxt = safe_shell_output('pip', 'install', '-r', 'requirements.txt')
    # #     if not psuc:
    # #         return False, "'git pull' succeeded, but 'pip install' failed! {}".format(ptxt)
    # #     else:
    # #         txt += "\n\nSubsequent 'pip install' succeeded"
    # # return success, txt
    return safe_shell_output('git', 'pull', 'origin', 'master')

def shell_restart_service():
    #return safe_shell_output('systemctl', 'restart', 'helheimr-heating.service')
    # Must use sudo because the service user is 'pi'.
    # Fortunately, there's https://raspberrypi.stackexchange.com/a/7137 to prevent
    # user interaction here ;-)
    success, txt = safe_shell_output('sudo', 'systemctl', 'restart', 'helheimr-heating.service')
    # Even if successful, there can be a problem due to scheduling:
    #   subprocess.CalledProcessError: Command ... died with <Signals.SIGTERM: 15> 
    # or similar, thus:
    if not success and (txt.find('Signals.SIGTERM') >= 0 or txt.find('Signals.SIGHUP') >= 0):
        return True, 'Already terminating the service...'
    return success, txt

def shell_shutdown(*args):
    # @see shell_restart_service() for comments on sudo'ing something
    success, txt = safe_shell_output('sudo', 'shutdown', *args)
    if not success and (txt.find('Signals.SIGTERM') >= 0 or txt.find('Signals.SIGHUP') >= 0):
        return True, 'Already terminating the service...'
    return success, txt


#######################################################################
## Message formatting

# def value(value, default=''):
#     """Returns the value if not none, otherwise an empty string."""
#     return default if value is None else value

def format_num(fmt, num, use_markdown=True):
        s = '{:' + fmt + '}'
        if use_markdown:
            s = '`' + s + '`'
        return s.format(num)


# Adapted from https://stackoverflow.com/a/40784706
# TODO: For more complex use cases, we need to support slicing
class circularlist(object):
    def __init__(self, size):
        self.index = 0
        self.size = size
        self._data = list()

    def append(self, value):
        if len(self._data) == self.size:
            self._data[self.index] = value
        else:
            self._data.append(value)
        self.index = (self.index + 1) % self.size

    def __getitem__(self, key):
        """Get element by index, relative to the current index"""
        if len(self._data) == self.size:
            return(self._data[(key + self.index) % self.size])
        else:
            return(self._data[key])

    def __repr__(self):
        """Return string representation"""
        return self._data.__repr__() + ' (' + str(len(self._data))+' items)'

    def __len__(self):
        return len(self._data)



################################################################################
# Timing code, similar to MATLAB's tic/toc
__tictoc_timers = {}
def tic(label='default'):
    """Start a timer."""
    __tictoc_timers[label] = timeit.default_timer()


def toc(label='default', seconds=False):
    """Stop timer and print elapsed time."""
    if label in __tictoc_timers:
        elapsed = timeit.default_timer() - __tictoc_timers[label]
        if seconds:
            print('[{:s}] Elapsed time: {:.3f} s'.format(label, elapsed))
        else:
            print('[{:s}] Elapsed time: {:.2f} ms'.format(label, 1000.0*elapsed))

def ttoc(label='default', seconds=False):
    """Stop timer and return elapsed time."""
    if label in __tictoc_timers:
        elapsed = timeit.default_timer() - __tictoc_timers[label]
        if seconds:
            return elapsed
        else:
            return 1000.0*elapsed


def toc_nsec(label='default', nsec=0.5, seconds=False):
    """Stop timer and print elapsed time (mute output for nsec seconds)."""
    if label in __tictoc_timers:
        elapsed = timeit.default_timer() - __tictoc_timers[label]
        if seconds:
            s = '[{:s}] Elapsed time: {:.3f} s'.format(label, elapsed)
        else:
            s = '[{:s}] Elapsed time: {:.2f} ms'.format(label, 1000.0*elapsed)
        log_nsec(s, nsec, label)


################################################################################
# Log only once every x sec
__log_timers = {}
def log_nsec(string, nsec, label='default'):
    """Display 'string' only once every nsec seconds (floating point number). Use it to avoid spamming your terminal."""
    if label in __log_timers:
        elapsed = timeit.default_timer() - __log_timers[label]
        if elapsed < nsec:
            return
    print(string)
    __log_timers[label] = timeit.default_timer()



################################################################################
# Math
#def rand_mod(m):
#    """Correctly sample a random number modulo m (avoiding modulo bias)"""
#    # python's random lib has random.uniform(a,b), a <= N <= b
#    return random.uniform(0, m-1)
#
# Problem in C/C++:
#   rand() returns a number in [0, RAND_MAX], assume RAND_MAX=10, we want mod 3:
#   rand() = 0, 3, 6, 9;  then mod3 = 0; prob(0) = 4/11
#   rand() = 1, 4, 7, 10; then mod3 = 1; prob(1) = 4/11
#   rand() = 2, 5, 8; then mod3 = 2; prob(2) = 3/11 !!!
#  see also: https://stackoverflow.com/a/10984975/400948


################################################################################
# Python language utils
def enum(**enums):
    """Utility to create enum-like classes, use it like: DrivingState = enum(STOPPED=1, FORWARD=2, BACKWARD=4)"""
    return type('Enum', (), enums)

def compare(a, b):
    """Replacement for Python 2.x cmp(), https://docs.python.org/3.0/whatsnew/3.0.html#ordering-comparisons"""
    return (a > b) - (a < b)

def compare_version_strings(v1, v2):
    """Compares version strings, returns -1/0/+1 if v1 less, equal or greater v2"""
    # https://stackoverflow.com/a/1714190/400948
    def normalize_version_string(v):
        return [int(x) for x in re.sub(r'(\.0+)*$','', v).split(".")]
    return compare(normalize_version_string(v1), normalize_version_string(v2))


# Make unicode strings, works for Python 2 & 3
try:
    to_unicode = unicode
except NameError:
    to_unicode = str

def slugify(s):
    """Converts a string to a slug (strip special characters, replace white space, convert to lowercase...) to be used for file names or URLs."""
    import unicodedata
    s = unicodedata.normalize('NFKD', to_unicode(s)).encode('ascii', 'ignore').decode('ascii')
    s = to_unicode(re.sub('[^\w\s-]', '', s).strip().lower())
    s = to_unicode(re.sub('[-\s]+', '-', s))
    return s


# regexp to extract numbers from strings taken from https://stackoverflow.com/questions/4289331/how-to-extract-numbers-from-a-string-in-python/4289415
def extract_integers(string):
    """Extract all integers from the string into a list (used to parse the CMI gateway's cgi output)."""
    return [int(t) for t in re.findall(r'\d+', string)]


def extract_floats(string):
    """Extract all real numbers from the string into a list (used to parse the CMI gateway's cgi output)."""
    return [float(t) for t in re.findall(r'[-+]?[.]?[\d]+(?:,\d\d\d)*[\.]?\d*(?:[eE][-+]?\d+)?', string)]


def find_first_index(l, x):
    """Returns the first index of element x within the list l."""
    for idx in range(len(l)):
        if l[idx] == x:
            return idx
    raise ValueError("'{}' is not in list".format(x))


def find_last_index(l, x):
    """Returns the last index of element x within the list l"""
    for idx in reversed(range(len(l))):
        if l[idx] == x:
            return idx
    raise ValueError("'{}' is not in list".format(x))


def argsort(seq, indices_only=False):
    """Returns the sorted indices and the sorted array (seq) if indices_only=False."""
    if indices_only:
        return sorted(range(len(seq)), key=seq.__getitem__)
    else:
        # https://stackoverflow.com/questions/7851077/how-to-return-index-of-a-sorted-list
        from operator import itemgetter
        return zip(*sorted(enumerate(seq), key=itemgetter(1)))


################################################################################
# OS interaction
def is_tool(name):
    """Check whether `name` is on PATH and marked as executable."""
    if sys.version_info >= (3,3):
        # Taken from https://stackoverflow.com/a/34177358
        from shutil import which
        return which(name) is not None
    else:
        # Search the PATH variable, taken from https://stackoverflow.com/a/5227009
        for path in os.environ['PATH'].split(os.pathsep):
            if os.path.exists(os.path.join(path, name)):
                return True
        return False
 

################################################################################
# Data validation (e.g. argument parsing)

def check_positive_int(value):
    iv = int(value)
    if iv <= 0:
        raise ValueError('{} must be > 0'.format(iv))
    return iv


def check_positive_real(value):
    fv = float(value)
    if fv <= 0:
        raise ValueError('{} must be > 0.0'.format(iv))
    return fv