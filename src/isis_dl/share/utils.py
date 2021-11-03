#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import inspect
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from functools import wraps
from queue import PriorityQueue
from typing import Union, Dict, Callable, Optional, List, Tuple
from urllib.parse import unquote

import requests

from isis_dl.share.settings import working_dir_location, whitelist_file_name_location, \
    blacklist_file_name_location, log_file_location, is_windows, log_clear_screen, settings_file_location, download_dir_location, password_dir, intern_dir_location, \
    log_dir_location, course_name_to_id_file_location, clear_password_file, sleep_time_for_isis, debug_mode


def get_args():
    def check_positive(value):
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This programs downloads all courses from your ISIS page.""")

    parser.add_argument("-V", "--version", help="Print the version number and exit", action="store_true")
    parser.add_argument("-v", "--verbose", help="Enable debug output", action="store_true")
    parser.add_argument("-n", "--num-threads", help="The number of threads which download the content from an individual course.", type=check_positive,
                        default=4)
    parser.add_argument("-d", "--download-rate", help="Limits the download rate to {…}MiB/s", type=float, default=None)

    parser.add_argument("-o", "--overwrite", help="Overwrites all existing files i.e. re-downloads them all.", action="store_true")
    parser.add_argument("-W", "--whitelist", help="A whitelist of course ID's. ", type=int, nargs="*")
    parser.add_argument("-B", "--blacklist", help="A blacklist of course ID's. Blacklist takes precedence over whitelist.", type=int, nargs="*")

    parser.add_argument("-l", "--log", help="Dump the output to the logfile", action="store_true")

    # Crypt options
    parser.add_argument("-p", "--prompt", help="Force the encryption prompt.", action="store_true")

    parser.add_argument("-b", "--build-checksums", help="Builds the checksums of all existent files and exits", action="store_true")

    if debug_mode:
        parser.add_argument("-t", "--test-checksums", help="Builds the checksums of all existent files and exits. Then checks if any collisions occurred.\nThis is meant as a debug feature.",
                            action="store_true")

    the_args, unknown = parser.parse_known_args()

    if unknown:
        print("I did not recognize the following arguments:\n" + "\n".join(unknown) + "\nI am going to ignore them.")

    # Store the white- / blacklist in args such that it only has to be evaluated once
    def make_list_from_file(filename: str) -> List[int]:
        try:
            with open(path(filename)) as f:
                return [int(item.strip()) for item in f.readlines() if item]
        except FileNotFoundError:
            return []

    whitelist = make_list_from_file(whitelist_file_name_location)
    blacklist = make_list_from_file(blacklist_file_name_location)

    whitelist.extend(the_args.whitelist or [])
    blacklist.extend(the_args.blacklist or [])

    the_args.whitelist = whitelist or [True]
    the_args.blacklist = blacklist

    return the_args


def startup():
    def prepare_dir(p):
        os.makedirs(path(p), exist_ok=True)

    def prepare_file(p):
        if not os.path.exists(path(p)):
            with open(path(p), "w"):
                pass

    def create_link_to_settings_file(file: str):
        fp = path(settings_file_location)

        def restore_link():
            os.symlink(file, fp)

        # TODO: What if link is invalid
        if os.path.exists(fp):
            if os.path.realpath(fp) != file:
                os.remove(fp)
                restore_link()
        else:
            restore_link()

    prepare_dir(download_dir_location)
    prepare_dir(intern_dir_location)
    prepare_dir(password_dir)
    prepare_dir(log_dir_location)

    prepare_file(course_name_to_id_file_location)
    prepare_file(clear_password_file)

    import isis_dl
    create_link_to_settings_file(os.path.abspath(isis_dl.share.settings.__file__))
    prepare_file(whitelist_file_name_location)
    prepare_file(blacklist_file_name_location)


def get_logger(debug_level: Optional[int] = None):
    """
    Creates the logger
    """
    # disable DEBUG messages from various modules
    logging.getLogger("urllib3").propagate = False
    logging.getLogger("selenium").propagate = False
    logging.getLogger("matplotlib").propagate = False
    logging.getLogger("PIL").propagate = False
    logging.getLogger("oauthlib").propagate = False
    logging.getLogger("requests_oauthlib.oauth1_auth").propagate = False

    logger = logging.getLogger(__name__)
    logger.propagate = False

    debug_level = debug_level or logging.DEBUG if args.verbose else logging.INFO
    logger.setLevel(debug_level)

    # File handling
    if args.log:
        fh = logging.FileHandler(path(log_file_location))
        fh.setLevel(debug_level)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(formatter)

        logger.addHandler(fh)

    if not is_windows:
        # Add a colored console handler. This only works on UNIX, however I use that. If you don't maybe reconsider using windows :P
        import coloredlogs

        coloredlogs.install(level=debug_level, logger=logger, fmt="%(asctime)s - [%(levelname)s] - %(message)s")

    else:
        # Windows users don't have colorful logs :(
        # Legacy solution that should work for windows.
        #
        # Warning: This is untested.
        #   I think it should work but if not, feel free to submit a bug report!

        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(debug_level)

        console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
        ch.setFormatter(console_formatter)

        logger.addHandler(ch)

    logger.info("Starting up…")

    return logger


def path(*args) -> str:
    return os.path.join(working_dir_location, *args)


def sanitize_name_for_dir(name: str) -> str:
    name = unquote(name)
    return name.replace("/", "-")


def clear_screen():
    if not log_clear_screen:
        return

    os.system("cls") if is_windows else os.system("clear")


def _get_func_session(func, *args, **kwargs) -> requests.Response:
    while True:
        try:
            return func(*args, **kwargs)  # type: ignore

        except requests.exceptions.ConnectionError:
            logger.warning(f"ISIS is complaining about the number of downloads (I am ignoring it). Consider dropping the thread count. Sleeping for {sleep_time_for_isis}s ")
            pass


def get_url_from_session(sess: requests.Session, *args, **kwargs) -> requests.Response:
    return _get_func_session(sess.get, *args, **kwargs)


def get_head_from_session(sess: requests.Session, *args, **kwargs) -> requests.Response:
    return _get_func_session(sess.head, *args, **kwargs)


def get_text_from_session(sess: requests.Session, *args, **kwargs) -> Optional[str]:
    if (s := get_url_from_session(sess, *args, **kwargs)).ok:
        return s.text

    return None


# Adapted from https://stackoverflow.com/a/5929165 and https://stackoverflow.com/a/36944992
def debug_time(str_to_put: Optional[str] = None, func_to_call: Optional[Callable[[object], str]] = None, debug_level: int = logging.DEBUG):
    def decorator(function):
        @wraps(function)
        def _self_impl(self, *method_args, **method_kwargs):
            logger.log(debug_level, f"Starting: {str_to_put if func_to_call is None else func_to_call(self)}")
            s = time.time()

            method_output = function(self, *method_args, **method_kwargs)
            logger.log(debug_level, f"Finished: {str_to_put if func_to_call is None else func_to_call(self)} in {time.time() - s:.3f}s")

            return method_output

        def _impl(*method_args, **method_kwargs):
            logger.log(debug_level, f"Starting: {str_to_put}")
            s = time.time()

            method_output = function(*method_args, **method_kwargs)
            logger.log(debug_level, f"Finished: {str_to_put} in {time.time() - s:.3f}s")

            return method_output

        if "self" in inspect.getfullargspec(function).args:
            return _self_impl

        return _impl

    return decorator


class OnKill:
    _funcs: PriorityQueue[Tuple[int, Callable[[], None]]] = PriorityQueue()
    _min_priority = 0
    _already_killed = False

    def __init__(self):
        signal.signal(signal.SIGINT, OnKill.exit)
        signal.signal(signal.SIGABRT, OnKill.exit)
        signal.signal(signal.SIGTERM, OnKill.exit)

        if is_windows:
            pass
        else:
            signal.signal(signal.SIGQUIT, OnKill.exit)  # type: ignore
            signal.signal(signal.SIGHUP, OnKill.exit)  # type: ignore

    @staticmethod
    def add(func, priority: Optional[int] = None):
        if priority is None:
            # Generate a new priority → max priority
            priority = OnKill._min_priority - 1

        OnKill._min_priority = min(priority, OnKill._min_priority)

        OnKill._funcs.put((priority, func))

    @staticmethod
    @atexit.register
    def exit(sig=None, frame=None):
        if OnKill._already_killed and sig is not None:
            logger.info("Alright, stay calm. I am skipping cleanup and exiting! This *will* lead to corrupted files!")
            os._exit(1)

        if sig is not None:
            sig = signal.Signals(sig)
            logger.warning(f"Noticed signal {sig.name} ({sig.value}). Cleaning up…")
            logger.debug("If you *really* need to exit please send another signal!")
            OnKill._already_killed = True

        for _ in range(OnKill._funcs.qsize()):
            func: Callable[[], None]
            _, func = OnKill._funcs.get_nowait()
            # try:
            func()
            # except:  # type: ignore
            # logger.error(f"The function {func.__name__} did not succeed.")


def on_kill(priority: Optional[int] = None):
    def decorator(function):
        # Expects the method to have *no* args
        @wraps(function)
        def _impl(*_):
            return function()

        OnKill.add(_impl, priority)
        return _impl

    return decorator


# Shared between modules.
@dataclass
class User:
    username: str
    password: str

    def __repr__(self):
        return f"{self.username}: {self.password}"

    def __str__(self):
        return f"\"{self.username}\""

    def dump(self):
        return self.username + "\n" + self.password + "\n"


# TODO: Probably delete
@dataclass
class Video:
    name: str
    collection_name: Union[str, None] = None
    url: Union[str, None] = None
    created: Union[str, None] = None
    approximate_filename: Union[str, None] = None

    @classmethod
    def from_dict(cls, content: Dict[str, str]):
        return cls(content["title"], content["collectionname"], content["url"], content["timecreated"])

    def __post_init__(self):
        self.name = sanitize_name_for_dir(self.name)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == other
        return self.__class__ == other.__class__ and self.name == other.name

    def __lt__(self, other):
        if self.__class__ != other.__class__:
            raise ValueError
        if self.created is None:
            if other.created is not None:
                return False
            return self.name > other.name
        return other.created > self.created


# Copied and adapted from https://stackoverflow.com/a/63839503
class HumanBytes:
    @staticmethod
    def format(num: Union[int, float, None]) -> Tuple[Optional[float], str]:
        """
        Human-readable formatting of bytes, using binary (powers of 1024) representation.

        Note: num > 0
        Will
            return None <=> num == None
        """

        if num is None:
            return None, "None"

        unit_labels = ["  B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
        last_label = unit_labels[-1]
        unit_step = 1024
        unit_step_thresh = unit_step - 0.5

        unit = None
        for unit in unit_labels:
            if num < unit_step_thresh:
                # Only return when under the rounding threshhold
                break
            if unit != last_label:
                num /= unit_step

        return num, unit


def e_format(
        nums: List[Union[int, float, str, None]],
        precision=2,
        ab: Optional[bool] = None,  # True = Remove - from output | False = Space others accordingly
        direction: str = ">",

        convert_func: Callable[[str], str] = lambda _: str(_)
) -> List[str]:
    #
    if ab is True:
        nums = [n if type(n) == str else abs(n) for n in nums]  # type: ignore

    # Convert the nums → strings
    final = []
    for num in nums:
        if num is None:
            final.append("None")
        if isinstance(num, str):
            final.append(convert_func(num))
        elif isinstance(num, (float, int)):
            final.append(f"{num:.{precision}f}")

    max_len = max([len(item) for item in final])

    # Pad the strings
    final = [f"{item:{' '}{direction}{max_len}}" for item in final]

    return final


startup()
OnKill()
args = get_args()
logger = get_logger()
