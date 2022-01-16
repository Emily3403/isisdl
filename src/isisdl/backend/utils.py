#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import os
import random
import signal
import string
import sys
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from queue import PriorityQueue
from typing import Union, Callable, Optional, List, Tuple, Dict, Any, Set, TYPE_CHECKING
from urllib.parse import unquote

import colorama

import isisdl
from isisdl.backend.database_helper import DatabaseHelper, ConfigHelper
from isisdl.settings import working_dir_location, is_windows, settings_file_location, course_dir_location, intern_dir_location, checksum_algorithm, checksum_base_skip, checksum_num_bytes, \
    testing_download_video_size, testing_download_documents_size

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer


def get_args_main() -> argparse.Namespace:
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


def get_args(file: str) -> argparse.Namespace:
    return get_args_main()


def startup() -> None:
    def prepare_dir(p: str) -> None:
        os.makedirs(path(p), exist_ok=True)

    prepare_dir(course_dir_location)
    prepare_dir(intern_dir_location)

    import isisdl

    def restore_link() -> None:
        try:
            os.remove(other_settings_file)
        except OSError:
            pass

        if not is_windows:
            # Sym-linking isn't really supported on Windows / not in a uniform way. Thus, I am not doing that.
            os.symlink(actual_settings_file, other_settings_file)

    actual_settings_file = os.path.abspath(isisdl.settings.__file__)
    other_settings_file = path(settings_file_location)

    if os.path.islink(other_settings_file):
        if os.path.realpath(other_settings_file) != actual_settings_file:
            restore_link()
    else:
        # Damaged link → Either doesn't exist / broken
        restore_link()


def clear() -> None:
    if is_windows:
        os.system('cls')
    else:
        os.system('clear')


def path(*args: str) -> str:
    return os.path.join(working_dir_location, *args)


def sanitize_name(name: str, filename_scheme: Optional[str] = None) -> str:
    # Remove unnecessary whitespace
    name = name.strip()
    name = unquote(name)

    filename_scheme = filename_scheme or config_helper.get_or_default_filename_scheme()

    # First replace umlaute
    for a, b in {"ä": "a", "ö": "o", "ü": "u"}.items():
        name = name.replace(a, b)
        name = name.replace(a.upper(), b.upper())

    # Now start to add chars that don't fit.
    char_string = ""

    if filename_scheme >= "0":
        if is_windows:
            for char in "<>:\"/\\|?*":
                name = name.replace(char, "")

            return name
        else:
            return name.replace("/", "")

    if filename_scheme >= "1":
        # Now replace any remaining funny symbols with a `?`
        name = name.encode("ascii", errors="replace").decode()

        char_string += r"""!"#$%&'()*+,/:;<=>?@[\]^`{|}~"""

    name = name.translate(str.maketrans(char_string, "\0" * len(char_string)))

    # This is probably a suboptimal solution, but it works…
    final = list(name)

    whitespaces = set(string.whitespace + "_")
    i = 0
    while i < len(final):
        char = final[i]

        if char == "\0" or char in whitespaces:
            final.pop(i)

            if char in whitespaces:
                if i < len(final):
                    final[i] = final[i].upper()

            continue

        i += 1

    return "".join(final)


def get_input(message: str, allowed: Set[str]) -> str:
    while True:
        choice = input(message)
        if choice in allowed:
            break

        print(f"\nUnhandled character: {choice!r} is not in the expected: {allowed}.\nPlease try again:\n\n")

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

        if sig is not None:
            sig = signal.Signals(sig)
            if isisdl.backend.request_helper.downloading_files:
                OnKill._already_killed = True
            else:
                os._exit(sig.value)

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


# Shared between modules.
@dataclass
class User:
    username: str
    password: str

    @staticmethod
    def sanitize_name(name: str) -> str:
        # uwu
        if name == "".join(chr(item) for item in [109, 97, 116, 116, 105, 115, 51, 52, 48, 51]):
            return "".join(chr(item) for item in [101, 109, 105, 108, 121, 51, 52, 48, 51])

        return name

    @property
    def sanitized_username(self) -> str:
        return self.sanitize_name(self.username)

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


startup()
OnKill()
database_helper = DatabaseHelper()
config_helper = ConfigHelper()

args = get_args(os.path.basename(sys.argv[0]))

# Windows specific color codes…
colorama.init()
