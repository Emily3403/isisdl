#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import random
import signal
import string
import subprocess
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from queue import PriorityQueue
from typing import Union, Callable, Optional, List, Tuple, Dict, Any, Set, TYPE_CHECKING, cast
from urllib.parse import unquote

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.settings import working_dir_location, is_windows, checksum_algorithm, checksum_base_skip, checksum_num_bytes, \
    testing_download_video_size, testing_download_documents_size, example_config_file_location, config_dir_location, database_file_location, status_time, video_size_discover_num_threads, \
    status_progress_bar_resolution, download_progress_bar_resolution, config_file_location, is_first_time, is_autorun, parse_config_file, lock_file_location, enable_lock, error_file_location, \
    error_directory_location

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer

error_text = "\033[1;91mError!\033[0m"


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This program downloads all content of your ISIS page.""")

    parser.add_argument("-V", "--version", help="Print the version number and exit", action="store_true")
    parser.add_argument("-v", "--verbose", help="Enable debug output\n ", action="store_true")
    parser.add_argument("-n", "--num-threads", help="The number of threads which download the files\n ", type=int, default=3, metavar="num")
    parser.add_argument("-d", "--download-rate", help="Limits the download rate to {num} MiB/s\n ", type=float, default=None, metavar="num")
    parser.add_argument("-o", "--overwrite", help="Overwrites all existing files\n ", action="store_true")

    parser.add_argument("-w", "--whitelist", help="A whitelist of course ID's.\n ", nargs="+", type=int, metavar="ID")
    parser.add_argument("-b", "--blacklist", help="A blacklist of course ID's.\n ", nargs="+", type=int, metavar="ID")

    parser.add_argument("-dv", "--disable-videos", help="Disables downloading of videos\n ", action="store_true")
    parser.add_argument("-dd", "--disable-documents", help="Disables downloading of documents", action="store_true")

    the_args, unknown = parser.parse_known_args()

    return the_args


class Config:
    password_encrypted: Optional[bool]
    username: Optional[str]
    password: Optional[str]

    whitelist: Optional[List[int]]
    blacklist: Optional[List[int]]

    download_videos: bool
    filename_replacing: bool
    throttle_rate: int
    throttle_rate_autorun: int
    update_policy: Optional[str]
    telemetry_policy: bool

    default_config: Dict[str, Union[bool, str, int, None]] = {
        "password_encrypted": False,
        "username": None,
        "password": None,

        "whitelist": None,
        "blacklist": None,

        "download_videos": True,
        "filename_replacing": False,
        "throttle_rate": None,
        "throttle_rate_autorun": None,
        "update_policy": "install_pip",
        "telemetry_policy": True,
    }

    __slots__ = tuple(
        k for k in default_config
    )

    _user: Dict[str, Union[bool, str, int, None]] = {k: None for k in default_config}
    _stored: Dict[str, Union[bool, str, int, None]] = {k: None for k in default_config}
    _backup: Dict[str, Union[bool, str, int, None]] = {k: None for k in default_config}
    _in_backup: bool = False

    def __init__(self) -> None:
        config_file_data = parse_config_file()
        stored_config = database_helper.get_config()

        Config._user.update(stored_config)
        Config._user.update(config_file_data)
        Config._stored.update(stored_config)

        for name in self.__slots__:
            super().__setattr__(name, next(iter(item for item in [config_file_data[name], stored_config[name]] if item is not None), self.default_config[name]))

        def set_list(name: str) -> None:
            if getattr(args, name):
                new_list = (getattr(self, name) or []) + getattr(args, name)
                super(Config, self).__setattr__(name, new_list)

        set_list("whitelist")
        set_list("blacklist")

    def __setattr__(self, key: str, value: Union[bool, str, int, None]) -> None:
        super().__setattr__(key, value)
        if not self._in_backup:
            Config._user[key] = value
            Config._stored[key] = value
            database_helper.set_config(self._stored)

    @staticmethod
    def default(attr: str) -> Any:
        return Config.default_config[attr]

    @staticmethod
    def user(attr: str) -> Any:
        return Config._user[attr]

    def to_dict(self) -> Dict[str, Union[bool, str, int, None]]:
        return {name: getattr(self, name) for name in self.__slots__}

    def start_backup(self) -> None:
        Config._backup = self.to_dict()
        Config._in_backup = True

    def restore_backup(self) -> None:
        Config._in_backup = False
        for name in self.__slots__:
            super().__setattr__(name, self._backup[name])


def encode_yaml(st: Union[bool, str, int, None]) -> str:
    if st is None:
        return "null"
    elif st is True:
        return "true"
    elif st is False:
        return "false"
    return str(st)


def generate_config_str(working_dir_location: str, database_file_location: str, filename_replacing: bool, download_videos: bool, whitelist: Optional[List[int]], blacklist: Optional[List[int]],
                        throttle_rate: Optional[int], throttle_rate_autorun: Optional[int], update_policy: Optional[str], telemetry_policy: bool, status_time: float,
                        video_size_discover_num_threads: int, status_progress_bar_resolution: int, download_progress_bar_resolution: int) -> str:
    return f"""---

# Any values you overwrite here will take precedence over *any* otherwise provided value.


# The directory where everything lives in.
# Possible values {{any absolute posix path}}
working_dir_location: {working_dir_location}

# The name of the SQlite Database (located in `working_dir_location`) used for storing metadata about files + config.
# Possible values {{any posix path}}
database_file_location: {database_file_location}


# Should videos be downloaded on this device?
# Possible values {{"true", "false"}}
download_videos: {encode_yaml(download_videos)}


# Should the filename be replaced with a sanitized version?
# Possible values {{"true", "false"}}
filename_replacing: {encode_yaml(filename_replacing)}


# The global whitelist of courses to be considered. Best set with `isisdl-config` and then extracted.
# Possible values {{"null", list[int] of course ID's}}
whitelist: {'null' if whitelist is None else whitelist}

# The global blacklist of courses to be considered. Best set with `isisdl-config` and then extracted.
# Possible values {{"null", list[int] of course ID's}}
blacklist: {'null' if blacklist is None else blacklist}


# The global throttle rate. Will take precedence over throttle_rate_autorun.
# Possible values {{"null", any integer}}
throttle_rate: {encode_yaml(throttle_rate)}

# The throttle rate for when `isisdl` automatically runs.
# Possible values {{"null", any integer}}
throttle_rate_autorun: {encode_yaml(throttle_rate_autorun)}


# How updates should be handled.
# Possible values {{"null", "install_pip", "install_github", "notify_pip", "notify_github"}}
update_policy: {encode_yaml(update_policy)}


# Should telemetry data be collected?
# Possible values {{"true", "false"}}
telemetry_policy: {encode_yaml(telemetry_policy)}


# The time waited between re-renders of the status message.
# If you have a fast terminal / PC you can easily set this value to 0.1 or even 0.01.
# Possible values {{any float}}
status_time: {status_time}


# Number of threads to use when discovering video file sizes (ISIS does not offer an API).
# Possible values {{any integer > 0}}
video_size_discover_num_threads: {video_size_discover_num_threads}


# The resolution of the initial progress bar.
# Possible values {{any integer > 0}}
status_progress_bar_resolution: {status_progress_bar_resolution}

# The resolution of the download progress bar.
# Possible values {{any integer > 0}}
download_progress_bar_resolution: {download_progress_bar_resolution}
"""


def generate_default_config_str() -> str:
    return generate_config_str(working_dir_location, database_file_location, Config.default("filename_replacing"), Config.default("download_videos"), Config.default("whitelist"),
                               Config.default("blacklist"), Config.default("throttle_rate"), Config.default("throttle_rate_autorun"), Config.default("update_policy"),
                               Config.default("telemetry_policy"), status_time, video_size_discover_num_threads, status_progress_bar_resolution, download_progress_bar_resolution)


def generate_current_config_str() -> str:
    return generate_config_str(working_dir_location, database_file_location, config.filename_replacing, config.download_videos, config.whitelist, config.blacklist, config.throttle_rate,
                               config.throttle_rate_autorun, config.update_policy, config.telemetry_policy, status_time, video_size_discover_num_threads, status_progress_bar_resolution,
                               download_progress_bar_resolution)


def startup() -> None:
    os.makedirs(path(), exist_ok=True)
    if os.path.exists(path(error_directory_location)) and not os.listdir(path(error_directory_location)):
        os.rmdir(path(error_directory_location))

    if not is_windows:
        os.makedirs(path(config_dir_location), exist_ok=True)

        default_config_str = generate_default_config_str()

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


def run_cmd_with_error(args: List[str]) -> None:
    result = subprocess.run(args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

    if result.returncode:
        print(error_text)
        print(f"The command `{' '.join(result.args)}` exited with exit code {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}")
        print("\nPress enter to continue")
        input()


def do_ffprobe(filename: str) -> Optional[Dict[str, Any]]:
    # This function is copied and adapted from ffmpeg-python: https://github.com/kkroening/ffmpeg-python
    args = ["ffprobe", "-show_format", "-show_streams", "-of", "json"]
    args += [filename]

    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        return None

    return cast(Dict[str, Any], json.loads(out.decode('utf-8')))


def is_h265(filename: str) -> Optional[bool]:
    probe = do_ffprobe(filename)
    if probe is None:
        return None

    video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
    if video_stream is None:
        return None

    if "codec_name" not in video_stream:
        # Later: Server
        return None

    return bool(video_stream["codec_name"] == "hevc")


def path(*args: str) -> str:
    return os.path.join(working_dir_location, *args)


def sanitize_name(name: str, replace_filenames: Optional[bool] = None) -> str:
    # Remove unnecessary whitespace
    name = name.strip()
    name = unquote(name)

    replace_filenames = replace_filenames or config.filename_replacing

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

        print(f"Unhandled character: {choice!r} is not in the expected {{" + ", ".join(repr(item) for item in sorted(list(allowed))) + "}\nPlease try again.\n")

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
        if sig is None:
            OnKill.do_funcs()
            return

        if OnKill._already_killed:
            print("Alright, stay calm. I am skipping cleanup and exiting!")
            os._exit(sig)

        OnKill._already_killed = True
        OnKill.do_funcs()
        os._exit(sig)

    @staticmethod
    def do_funcs() -> None:
        for _ in range(OnKill._funcs.qsize()):
            OnKill._funcs.get_nowait()[1]()


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

    global created_lock_file
    created_lock_file = True

    return False


created_lock_file = False


def acquire_file_lock_or_exit() -> None:
    if acquire_file_lock():
        print(f"I could not acquire the lock file: `{path(lock_file_location)}`\nIf you are certain that no other instance of `isisdl` is running, you may delete it.")

        if is_autorun:
            os._exit(1)

        print("\nIf you want, I can also delete it for you.\nDo you want me to do that? [y/n]")
        choice = get_input({"y", "n"})
        if choice == "y":
            os.remove(path(lock_file_location))
            acquire_file_lock()
        else:
            os._exit(1)


@on_kill(1)
def remove_lock_file() -> None:
    global created_lock_file
    if not enable_lock:
        return

    if not created_lock_file:
        return

    if not os.path.exists(path(lock_file_location)):
        print("I could not remove the Lock file… why?")
        return

    os.remove(path(lock_file_location))


# Shared between modules.
class User:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

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
    def format(num: float) -> Tuple[float, str]:
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

    @staticmethod
    def format_str(num: float) -> str:
        n, unit = HumanBytes.format(num)
        return f"{n:.2f} {unit}"

    @staticmethod
    def format_pad(num: float) -> str:
        n, unit = HumanBytes.format(num)
        return f"{f'{n:.2f}'.rjust(6)} {unit}"


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
    print(f"I have logged this error to the file\n{file_location}")

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
args = get_args()
config = Config()
