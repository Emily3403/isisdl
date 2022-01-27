#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import os
import random
import signal
import string
import traceback
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from queue import PriorityQueue
from typing import Union, Callable, Optional, List, Tuple, Dict, Any, Set, TYPE_CHECKING, Mapping, TypeVar
from urllib.parse import unquote

import colorama
from yaml import safe_load

import isisdl
from isisdl.backend.database_helper import DatabaseHelper
from isisdl.settings import working_dir_location, is_windows, checksum_algorithm, checksum_base_skip, checksum_num_bytes, \
    testing_download_video_size, testing_download_documents_size, example_config_file_location, config_dir_location, database_file_location, status_time, status_chop_off, sync_database_num_threads, \
    first_progress_bar_resolution, download_progress_bar_resolution, config_file_location, is_first_time, is_autorun, parse_config_file, lock_file_location, enable_lock, error_file_location, \
    error_directory_location

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer

error_text = "\033[1;91mError!\033[0m"

def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This program downloads all courses from your ISIS page.""")

    parser.add_argument("-V", "--version", help="Print the version number and exit", action="store_true")
    parser.add_argument("-v", "--verbose", help="Enable debug output", action="store_true")
    parser.add_argument("-n", "--num-threads", help="The number of threads which download the content from an individual course.", type=int, default=3)
    parser.add_argument("-d", "--download-rate", help="Limits the download rate to {…}MiB/s", type=float, default=None)
    parser.add_argument("-o", "--overwrite", help="Overwrites all existing files i.e. re-downloads them all.", action="store_true")

    parser.add_argument("-w", "--whitelist", help="A whitelist of course ID's. ", nargs="*")
    parser.add_argument("-b", "--blacklist", help="A blacklist of course ID's. Blacklist takes precedence over whitelist.", nargs="*")

    parser.add_argument("-dv", "--disable-videos", help="Disables downloading of videos", action="store_true")
    parser.add_argument("-dd", "--disable-documents", help="Disables downloading of documents", action="store_true")

    the_args, unknown = parser.parse_known_args()

    if the_args.disable_videos:
        the_args.num_threads *= 2

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


def get_default_config() -> Dict[str, Union[str, bool, None]]:
    return {
        "password_encrypted": False,
        "username": None,
        "password": None,
        "filename_replacing": False,
        "throttle_rate": None,
        "throttle_rate_autorun": None,
        "update_policy": "pip",
        "telemetry_policy": True,
    }


_KT = TypeVar("_KT")  # key type
_VT = TypeVar("_VT")  # value type


class Config(dict, Mapping[_KT, _VT]):  # type: ignore
    def __setitem__(self, key: str, value: Union[bool, str, None]) -> None:
        super().__setitem__(key, value)
        database_helper.set_config(self)


def get_config() -> Config[str, Union[bool, str, None]]:
    default_config = get_default_config()

    _config_file_data = parse_config_file()
    config_file_data = {}

    # Only get entries that are present in the default config
    for k in default_config:
        if k in _config_file_data:
            config_file_data[k] = _config_file_data[k]

    stored_config = database_helper.get_config()

    # TODO: Validate the config

    return Config({**default_config, **stored_config, **config_file_data})


def startup() -> None:
    os.makedirs(path(), exist_ok=True)
    if os.path.exists(path(error_directory_location)) and not os.listdir(path(error_directory_location)):
        os.rmdir(path(error_directory_location))

    if not is_windows:
        os.makedirs(path(config_dir_location), exist_ok=True)

    default_config = get_default_config()

    def encode(st: Union[str, bool, None]) -> str:
        if st is None:
            return "null"
        elif st is True:
            return "yes"
        elif st is False:
            return "no"
        return str(st)

    default_config_str = f"""---

# You can overwrite any of the following values by un-commenting them.
# They will take precedence over *any* otherwise provided value.


# The directory where everything lives in.
# Possible values {{any posix path}}
#working_dir_location: {working_dir_location}

# The name of the SQlite Database (located in `working_dir_location`).
# Possible values {{any posix path}}
#database_file_location: {database_file_location}


# The way filenames are handled.
# Possible values: {{"yes", "no"}}
#filename_replacing: {encode(default_config["filename_replacing"])}


# If a throttle rate should be imposed (in MiB).
# Possible values {{"null", any integer}}
#throttle_rate: {encode(default_config["throttle_rate"])}

# The throttle rate for when `isisdl` automatically runs.
# throttle_rate_autorun: {encode(default_config["throttle_rate_autorun"])}


# How updates should be handled.
# Possible values {{"pip", "github", "no"}}
#update_policy: {encode(default_config["update_policy"])}


# If telemetry data should be collected.
# Possible values {{"yes", "no"}}
#telemetry_policy: {encode(default_config["telemetry_policy"])}


# The status message is replaced every ↓ seconds. If you are using e.g. alacritty values of 0.01 are possible.
# Possible values {{any float}}
#status_time: {status_time}


# Number of threads to use for the database requests when `isisdl-sync` is called
# Possible values {{any integer > 0}}
#sync_database_num_threads: {sync_database_num_threads}


# The number of spaces the first progress bar has
# Possible values {{any integer > 0}}
#first_progress_bar_resolution: {first_progress_bar_resolution}

# The number of spaces the second progress bar (for the downloads) has
# Possible values {{any integer > 0}}
#download_progress_bar_resolution: {download_progress_bar_resolution}
    """

    with open(example_config_file_location, "w") as f:
        f.write(default_config_str)

    if not os.path.exists(config_file_location):
        with open(config_file_location, "w") as f:
            f.write(f"# You probably want to start by copying {config_file_location} and adapting it.\n")


def clear() -> None:
    if is_windows:
        os.system('cls')
    else:
        os.system('clear')


def path(*args: str) -> str:
    return os.path.join(working_dir_location, *args)


def sanitize_name(name: str, replace_filenames: Optional[bool] = None) -> str:
    # Remove unnecessary whitespace
    name = name.strip()
    name = unquote(name)

    replace_filenames = replace_filenames or config["filename_scheme"]

    # First replace umlaute
    for a, b in {"ä": "a", "ö": "o", "ü": "u"}.items():
        name = name.replace(a, b)
        name = name.replace(a.upper(), b.upper())

    # Now start to add chars that don't fit.
    char_string = ""

    if replace_filenames is False:
        if is_windows:
            for char in "<>:\"/\\|?*":
                name = name.replace(char, "")

            return name
        else:
            return name.replace("/", "")

    # Now replace any remaining funny symbols with a `?`
    name = name.encode("ascii", errors="replace").decode()

    char_string += r"""!"#$%&'()*+,/:;<=>?@[\]^`{|}~"""

    name = name.translate(str.maketrans(char_string, "\0" * len(char_string)))

    # This is probably a suboptimal solution, but it works…
    str_list = list(name)
    final = []

    whitespaces = set(string.whitespace + "_-")
    i = 0
    next_upper = False
    while i < len(str_list):
        char = str_list[i]

        if char == "\0":
            pass
        elif char in whitespaces:
            next_upper = True

        else:
            if next_upper:
                final.append(char.upper())
                next_upper = False
            else:
                final.append(char)

        i += 1

    return "".join(final)


def get_input(allowed: Set[str]) -> str:
    while True:
        choice = input()
        if choice in allowed:
            break

        print(f"Unhandled character: {choice!r} is not in the expected {allowed}.\nPlease try again.\n")

    return choice


class OnKill:
    _funcs: PriorityQueue[Tuple[int, Callable[[], None]]] = PriorityQueue()
    _min_priority = 0
    _already_killed = False

    def __init__(self) -> None:
        signal.signal(signal.SIGINT, OnKill.exit)
        signal.signal(signal.SIGABRT, OnKill.exit)
        signal.signal(signal.SIGTERM, OnKill.exit)

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
        if OnKill._already_killed and sig is not None:
            print("Alright, stay calm. I am skipping cleanup and exiting!")
            print("I will redownload the files that are partially downloaded.")

            os._exit(sig)

        for _ in range(OnKill._funcs.qsize()):
            OnKill._funcs.get_nowait()[1]()

        if sig is not None:
            sig = signal.Signals(sig)
            if isisdl.backend.request_helper.downloading_files:
                OnKill._already_killed = True
            else:
                os._exit(sig.value)


def on_kill(priority: Optional[int] = None) -> Callable[[Any], Any]:
    def decorator(function: Any) -> Any:
        # Expects the method to have *no* args
        @wraps(function)
        def _impl(*_: Any) -> Any:
            return function()

        OnKill.add(_impl, priority)
        return _impl

    return decorator


def acquire_file_lock() -> bool:
    if not enable_lock:
        return False

    if os.path.exists(path(lock_file_location)):
        return True

    with open(path(lock_file_location), "w") as f:
        f.write("UwU")

    return False


def acquire_file_lock_or_exit() -> None:
    if acquire_file_lock():
        print(f"I could not acquire the lock file: `{path(lock_file_location)}`\nIf you are certain that no other instance is running, you may delete it.")

        if is_autorun:
            exit(1)

        print("\nIf you want, I can also delete it for you.\nDo you want me to do that? [y/n]")
        choice = get_input({"y", "n"})
        if choice == "y":
            os.remove(path(lock_file_location))
            acquire_file_lock()
        else:
            exit(1)


@on_kill(1)
def remove_lock_file() -> None:
    if not enable_lock:
        return

    if not os.path.exists(path(lock_file_location)):
        print("I could not remove the Lock file… why?")
        return

    os.remove(path(lock_file_location))


# Shared between modules.
@dataclass
class User:
    username: str
    password: str

    @staticmethod
    def sanitize_name(name: Optional[str]) -> Optional[str]:
        if name is None:
            return None

        # UwU
        if name == "".join(chr(item) for item in [109, 97, 116, 116, 105, 115, 51, 52, 48, 51]):
            return "".join(chr(item) for item in [101, 109, 105, 108, 121, 51, 52, 48, 51])

        return name

    @property
    def sanitized_username(self) -> str:
        return self.sanitize_name(self.username) or ""

    def __repr__(self) -> str:
        return f"{self.sanitized_username}: {self.password}"

    def __str__(self) -> str:
        return f"\"{self.sanitized_username}\""


def calculate_local_checksum(filename: Path) -> str:
    sha = checksum_algorithm()
    sha.update(str(os.path.getsize(filename)).encode())
    curr_char = 0
    with open(filename, "rb") as f:
        i = 1
        while True:
            f.seek(curr_char)
            data = f.read(checksum_num_bytes)
            curr_char += checksum_num_bytes
            if not data:
                break
            sha.update(data)

            curr_char += checksum_base_skip ** i
            i += 1

    return sha.hexdigest()


def calculate_online_checksum_file(file: Path, size: int) -> str:
    chunk = b""
    with file.open("rb") as f:
        while len(chunk) < size:
            chunk += f.read(size - len(chunk))

    return checksum_algorithm(chunk + str(size).encode()).hexdigest()


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


def _course_downloader_transformation(pre_containers: List[PreMediaContainer]) -> List[PreMediaContainer]:
    possible_videos: List[PreMediaContainer] = []
    possible_documents: List[PreMediaContainer] = []

    # Get a random sample of lower half
    video_containers = sorted([item for item in pre_containers if item.is_video], key=lambda x: x.size)
    video_containers = video_containers[:int(len(video_containers) / 2)]

    document_containers = [item for item in pre_containers if not item.is_video]

    random.shuffle(video_containers)
    random.shuffle(document_containers)

    def maybe_add(lst: List[Any], file: PreMediaContainer, max_size: int) -> bool:
        maybe_new_size = sum(item.size for item in lst) + file.size
        if maybe_new_size > max_size:
            return True

        lst.append(file)
        return False

    # Select videos such that the total number of seconds does not overflow.
    for item in video_containers:
        if maybe_add(possible_videos, item, testing_download_video_size):
            break

    for item in document_containers:
        if maybe_add(possible_documents, item, testing_download_documents_size):
            break

    ret = possible_videos + possible_documents
    random.shuffle(ret)
    return ret


def generate_error_message() -> None:
    print("\nI have encountered the following Exception. I'm sorry this happened 😔\n")
    print(traceback.format_exc())

    file_location = path(error_directory_location, datetime.now().strftime(error_file_location))
    print(f"I have logged this error to the file\n`{file_location}`")

    os.makedirs(path(error_directory_location), exist_ok=True)

    with open(file_location, "w") as f:
        f.write(traceback.format_exc())

    os._exit(1)


# Don't create startup files
if is_first_time:
    if is_autorun:
        exit(1)

startup()
OnKill()
database_helper = DatabaseHelper()
config = get_config()

args = get_args()

# Windows specific color codes…
colorama.init()
