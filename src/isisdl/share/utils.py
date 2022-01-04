#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import inspect
import logging
import os
import signal
import string
import sys
import time
from dataclasses import dataclass
from functools import wraps
from multiprocessing import current_process
from queue import PriorityQueue
from typing import Union, Callable, Optional, List, Tuple, Dict, Iterable, cast, Any
from urllib.parse import unquote

from isisdl.backend.database_helper import DatabaseHelper, ConfigHelper
from isisdl.share.settings import working_dir_location, \
    log_file_location, is_windows, settings_file_location, download_dir_location, password_dir, intern_dir_location, \
    log_dir_location, clear_password_file, checksum_algorithm, checksum_base_skip

static_fail_msg = "\n\nIt seams as if I had done my testing sloppy. I'm sorry :(\n" \
                  "Please open a issue at https://github.com/Emily3403/isisdl/issues with a screenshot of this text.\n" \
                  "You can disable this assertion by rerunning with the '-a' flag."


def get_args_main() -> argparse.Namespace:
    def check_positive(value: str) -> int:
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This program downloads all courses from your ISIS page.""")

    parser.add_argument("-V", "--version", help="Print the version number and exit", action="store_true")
    parser.add_argument("-v", "--verbose", help="Enable debug output", action="store_true")
    parser.add_argument("-n", "--num-threads", help="The number of threads which download the content from an individual course.", type=check_positive, default=4)
    parser.add_argument("-d", "--download-rate", help="Limits the download rate to {…}MiB/s", type=float, default=None)
    parser.add_argument("-o", "--overwrite", help="Overwrites all existing files i.e. re-downloads them all.", action="store_true")

    parser.add_argument("-w", "--whitelist", help="A whitelist of course ID's. ", nargs="*")
    parser.add_argument("-b", "--blacklist", help="A blacklist of course ID's. Blacklist takes precedence over whitelist.", nargs="*")

    parser.add_argument("-l", "--log", help="Dump the output to the logfile", action="store_true")
    parser.add_argument("-a", "--enable-assertions", help="Enables all debug assertions. Defaults to true.", action="store_false")

    parser.add_argument("-dv", "--disable-videos", help="Disables downloading of videos", action="store_true")
    parser.add_argument("-dd", "--disable-documents", help="Disables downloading of documents", action="store_true")

    # Crypt options
    parser.add_argument("-p", "--prompt", help="Force the encryption prompt.", action="store_true")  # TODO: Remove

    the_args, unknown = parser.parse_known_args()

    if unknown:
        print("I did not recognize the following arguments:\n" + "\n".join(unknown) + "\nI am going to ignore them.")

    course_id_mapping: Dict[str, int] = dict(database_helper.get_course_name_and_ids())

    def add_arg_to_list(lst: Optional[List[Union[str]]]) -> List[int]:
        if lst is None:
            return []

        ret = set()
        for item in lst:
            try:
                ret.add(int(item))
            except ValueError:
                for course, num in course_id_mapping.items():
                    if item.lower() in course.lower():
                        ret.add(int(num))

        return list(ret)

    whitelist: List[int] = []
    blacklist: List[int] = []

    whitelist.extend(add_arg_to_list(the_args.whitelist))
    blacklist.extend(add_arg_to_list(the_args.blacklist))

    the_args.whitelist = whitelist or [True]
    the_args.blacklist = blacklist

    return the_args


def get_args(file: str) -> argparse.Namespace:
    return get_args_main()


def startup() -> None:
    def prepare_dir(p: str) -> None:
        os.makedirs(path(p), exist_ok=True)

    def prepare_file(p: str) -> None:
        if not os.path.exists(path(p)):
            with open(path(p), "w"):
                pass

    def create_link_to_settings_file(file: str) -> None:
        fp = path(settings_file_location)

        def restore_link() -> None:
            try:
                os.remove(fp)
            except OSError:
                pass

            if not is_windows:
                # Sym-linking isn't really supported on windows / not in a uniform way. I am not doing that.
                os.symlink(file, fp)

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

    prepare_file(clear_password_file)

    import isisdl
    create_link_to_settings_file(os.path.abspath(isisdl.share.settings.__file__))


def get_logger(debug_level: Optional[int] = None) -> logging.Logger:
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


class CriticalError(Exception):
    pass


def path(*args: str) -> str:
    return os.path.join(working_dir_location, *args)


def sanitize_name(name: str) -> str:
    # Remove unnecessary whitespace
    name = name.strip()
    name = unquote(name)

    if _filename_scheme >= "0":
        name = name.replace("/", "-")

    if _filename_scheme >= "1":
        # Now replace any remaining funny symbols with a `?`
        name = name.encode("ascii", errors="replace").decode()

        # Now replace all known "bad" ascii chars with a symbol
        char_mapping = {
            ".": string.whitespace + "_" + r"""#%&/:;<=>@\^`|~-$"'?""",
            "(": "[{",
            ")": "]}",
        }

        for char, mapping in char_mapping.items():
            name = name.translate(str.maketrans(mapping, char * len(mapping)))

    return name


# Adapted from https://stackoverflow.com/a/5929165 and https://stackoverflow.com/a/36944992
def debug_time(str_to_put: Optional[str] = None, func_to_call: Optional[Callable[[object], str]] = None, debug_level: int = logging.DEBUG) -> Callable[[Any], Any]:
    def decorator(function: Any) -> Any:
        @wraps(function)
        def _self_impl(self: Any, *method_args: Any, **method_kwargs: Any) -> Any:
            logger.log(debug_level, f"Starting: {str_to_put if func_to_call is None else func_to_call(self)}")
            s = time.perf_counter()

            method_output = function(self, *method_args, **method_kwargs)
            logger.log(debug_level, f"Finished: {str_to_put if func_to_call is None else func_to_call(self)} in {time.perf_counter() - s:.3f}s")

            return method_output

        def _impl(*method_args: Any, **method_kwargs: Any) -> Any:
            logger.log(debug_level, f"Starting: {str_to_put}")
            s = time.perf_counter()

            method_output = function(*method_args, **method_kwargs)
            logger.log(debug_level, f"Finished: {str_to_put} in {time.perf_counter() - s:.3f}s")

            return method_output

        if "self" in inspect.getfullargspec(function).args:
            return _self_impl

        return _impl

    return decorator


class OnKill:
    _funcs: PriorityQueue[Tuple[int, Callable[[], None]]] = PriorityQueue()
    _min_priority = 0
    _already_killed = False

    def __init__(self) -> None:
        signal.signal(signal.SIGINT, OnKill.exit)
        signal.signal(signal.SIGABRT, OnKill.exit)
        signal.signal(signal.SIGTERM, OnKill.exit)

        if is_windows:
            pass
        else:
            signal.signal(signal.SIGQUIT, OnKill.exit)
            signal.signal(signal.SIGHUP, OnKill.exit)

    @staticmethod
    def add(func: Any, priority: Optional[int] = None) -> None:
        if priority is None:
            # Generate a new priority → max priority
            priority = OnKill._min_priority - 1

        OnKill._min_priority = min(priority, OnKill._min_priority)

        OnKill._funcs.put((priority, func))

    @staticmethod
    @atexit.register
    def exit(sig: Optional[int] = None, frame: Any = None) -> None:
        from isisdl.backend.request_helper import CourseDownloader
        if OnKill._already_killed and sig is not None:
            logger.info("Alright, stay calm. I am skipping cleanup and exiting!")
            logger.info("This *will* lead to corrupted files!")

            os._exit(sig)

        if sig is not None:
            sig = signal.Signals(sig)
            logger.warning(f"Noticed signal {sig.name} ({sig.value}).")
            if CourseDownloader.downloading_files:
                logger.debug("If you *really* need to exit please send another signal!")
                OnKill._already_killed = True
            else:
                os._exit(sig.value)

        for _ in range(OnKill._funcs.qsize()):
            func: Callable[[], None]
            _, func = OnKill._funcs.get_nowait()
            func()


def on_kill(priority: Optional[int] = None) -> Callable[[Any], Any]:
    def decorator(function: Any) -> Any:
        # Expects the method to have *no* args
        @wraps(function)
        def _impl(*_: Any) -> Any:
            return function()

        OnKill.add(_impl, priority)
        return _impl

    return decorator


# Shared between modules.
@dataclass
class User:
    username: str
    password: str

    @property
    def sanitized_username(self) -> str:
        # Remove the deadname ^^
        if self.username == "".join(chr(item) for item in [109, 97, 116, 116, 105, 115, 51, 52, 48, 51]):
            return "emily3403"

        return self.username

    def __repr__(self) -> str:
        return f"{self.sanitized_username}: {self.password}"

    def __str__(self) -> str:
        return f"\"{self.sanitized_username}\""

    def dump(self) -> str:
        return self.username + "\n" + self.password + "\n"


def calculate_checksum(filename: str) -> str:
    sha = checksum_algorithm()
    sha.update(str(os.path.getsize(filename)).encode())
    curr_char = 0
    with open(filename, 'rb') as f:
        i = 1
        while True:
            f.seek(curr_char)
            data = f.read(1024)
            curr_char += 1024
            if not data:
                break
            sha.update(data)

            curr_char += checksum_base_skip ** i
            i += 1

    return sha.hexdigest()


# Copied and adapted from https://stackoverflow.com/a/63839503
class HumanBytes:
    @staticmethod
    def format(num: Union[int, float]) -> Tuple[float, str]:
        """
        Human-readable formatting of bytes, using binary (powers of 1024) representation.

        Note: num > 0
        """

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
        precision: int = 2,
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
database_helper = DatabaseHelper()
config_helper = ConfigHelper()

args = get_args(os.path.basename(sys.argv[0]))
logger = get_logger()


_filename_scheme = config_helper.get_filename_scheme()
