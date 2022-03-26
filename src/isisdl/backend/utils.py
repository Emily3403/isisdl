#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import platform
import random
import re
import shutil
import signal
import string
import subprocess
import stat
import sys
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from queue import PriorityQueue, Queue
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Callable, List, Tuple, Dict, Any, Set, TYPE_CHECKING, cast, NoReturn
from typing import Optional, Union
from urllib.parse import unquote, parse_qs, urlparse

import colorama
import distro as distro
import requests
from packaging import version
from packaging.version import Version, LegacyVersion
from requests import Session

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.settings import working_dir_location, is_windows, checksum_algorithm, checksum_base_skip, checksum_num_bytes, \
    testing_download_video_size, testing_download_documents_size, example_config_file_location, config_dir_location, database_file_location, status_time, extern_discover_num_threads, \
    status_progress_bar_resolution, download_progress_bar_resolution, config_file_location, is_first_time, is_autorun, parse_config_file, lock_file_location, enable_lock, error_file_location, \
    error_directory_location, systemd_dir_location, master_password, is_testing, timer_file_location, service_file_location, export_config_file_location, isisdl_executable, is_static
from isisdl.version import __version__

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer, RequestHelper
    from isisdl.backend.downloads import MediaType

error_text = "\033[1;91mError!\033[0m"


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This program downloads all content from your ISIS profile.""")

    parser.add_argument("-t", "--num-threads", help="The number of threads which download the files\n ", type=int, default=3, metavar="{num}")
    parser.add_argument("-d", "--download-rate", help="Limits the download rate to {num} MiB/s\n ", type=float, default=None, metavar="{num}")

    operations = parser.add_mutually_exclusive_group()

    operations.add_argument("-V", "--version", help="Print the version number and exit", action="store_true")
    operations.add_argument("--init", help="Guides you through the initial configuration and setup process.", action="store_true")
    operations.add_argument("--config", help="Guides you through addtitional configuration which focuses on what to download from ISIS.", action="store_true")
    operations.add_argument("--sync", help="Synchronizes the local database with ISIS. Will delete not existent or corrupted entries.", action="store_true")
    operations.add_argument("--compress", help="Starts ffmpeg and will compress all downloaded videos.", action="store_true")
    operations.add_argument("--subscribe", help="Subscribes you to *all* ISIS courses publicly available.", action="store_true")  # TODO
    operations.add_argument("--unsubscribe", help="Unsubscribes you from the courses you got subscribed by running `isisdl --subscribe`.", action="store_true")
    operations.add_argument("--export-config", help=f"Exports the config to {export_config_file_location}", action="store_true")

    if is_testing:
        return parser.parse_known_args()[0]

    return parser.parse_args()


class Config:
    password_encrypted: Optional[bool]
    username: Optional[str]
    password: Optional[str]

    whitelist: Optional[List[int]]
    blacklist: Optional[List[int]]
    renamed_courses: Optional[Dict[int, str]]
    make_subdirs: bool
    follow_links: bool

    download_videos: bool
    filename_replacing: bool
    timer_enable: bool
    throttle_rate: int
    throttle_rate_autorun: int
    update_policy: Optional[str]
    telemetry_policy: bool

    default_config: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {
        "password_encrypted": False,
        "username": None,
        "password": None,

        "whitelist": None,
        "blacklist": None,
        "renamed_courses": None,
        "make_subdirs": True,
        "follow_links": True,

        "download_videos": True,
        "filename_replacing": False,
        "timer_enable": True,
        "throttle_rate": None,
        "throttle_rate_autorun": None,
        "update_policy": "install_pip",
        "telemetry_policy": True,
    }

    __slots__ = tuple(default_config)

    _user: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {k: None for k in default_config}
    _stored: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {k: None for k in default_config}
    _backup: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {k: None for k in default_config}
    _in_backup: bool = False

    def __init__(self) -> None:
        config_file_data = parse_config_file()
        stored_config = database_helper.get_config()

        # Json only allows for keys to be strings (https://stackoverflow.com/a/8758771)
        # Set the keys manually back to ints, so we can work with them.

        for item in [config_file_data, stored_config]:
            if item["renamed_courses"] is not None:
                assert isinstance(item["renamed_courses"], dict)
                item["renamed_courses"] = {int(k): v for k, v in item["renamed_courses"].items()}

        Config._user.update(stored_config)
        Config._user.update(config_file_data)
        Config._stored.update(stored_config)

        for name in self.__slots__:
            super().__setattr__(name, next(iter(item for item in [config_file_data[name], stored_config[name]] if item is not None), self.default_config[name]))

    def __setattr__(self, key: str, value: Union[bool, str, int, None, Dict[int, str]]) -> None:
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

    def to_dict(self) -> Dict[str, Union[bool, str, int, None, Dict[int, str]]]:
        ret = {name: getattr(self, name) for name in self.__slots__}
        ret["username"] = User.sanitize_name(ret["username"])
        return ret

    def start_backup(self) -> None:
        Config._backup = self.to_dict()
        Config._in_backup = True

    def restore_backup(self) -> None:
        Config._in_backup = False
        for name in self.__slots__:
            super().__setattr__(name, self._backup[name])


def encode_yaml(st: Union[bool, str, int, None, Dict[int, str]]) -> str:
    if st is None:
        return "null"
    elif st is True:
        return "true"
    elif st is False:
        return "false"
    return str(st)


def generate_config_str(working_dir_location: str, database_file_location: str, master_password: str, filename_replacing: bool, download_videos: bool, whitelist: Optional[List[int]],
                        blacklist: Optional[List[int]], throttle_rate: Optional[int], throttle_rate_autorun: Optional[int], update_policy: Optional[str], telemetry_policy: bool, status_time: float,
                        video_size_discover_num_threads: int, status_progress_bar_resolution: int, download_progress_bar_resolution: int) -> str:
    return f"""---

# Any values you overwrite here will take precedence over *any* otherwise provided value.


# The directory where everything lives in.
# Possible values {{any absolute posix path}}
working_dir_location: {working_dir_location}

# The name of the SQlite Database (located in `working_dir_location`) used for storing metadata about files + config.
# Possible values {{any posix path}}
database_file_location: {database_file_location}

# The password to encrypt your password, if none is provided
# Possible values {{any string}}
master_password: {master_password}


# The time waited between re-renders of the status message.
# If you have a fast terminal / PC you can easily set this value to 0.1 or even 0.01.
# Possible values {{any float}}
status_time: {status_time}


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
    return generate_config_str(working_dir_location, database_file_location, master_password, Config.default("filename_replacing"), Config.default("download_videos"), Config.default("whitelist"),
                               Config.default("blacklist"), Config.default("throttle_rate"), Config.default("throttle_rate_autorun"), Config.default("update_policy"),
                               Config.default("telemetry_policy"), status_time, extern_discover_num_threads, status_progress_bar_resolution, download_progress_bar_resolution)


def generate_current_config_str() -> str:
    return generate_config_str(working_dir_location, database_file_location, master_password, config.filename_replacing, config.download_videos, config.whitelist, config.blacklist,
                               config.throttle_rate,
                               config.throttle_rate_autorun, config.update_policy, config.telemetry_policy, status_time, extern_discover_num_threads, status_progress_bar_resolution,
                               download_progress_bar_resolution)


def export_config() -> None:
    with open(export_config_file_location, "w") as f:
        f.write(generate_current_config_str())


def startup() -> None:
    os.makedirs(path(), exist_ok=True)
    if os.path.exists(path(error_directory_location)) and not os.listdir(path(error_directory_location)):
        os.rmdir(path(error_directory_location))

    if not is_windows:
        os.makedirs(path(config_dir_location), exist_ok=True)
        os.makedirs(systemd_dir_location, exist_ok=True)

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


def parse_google_drive_url(url: str) -> Optional[str]:
    """
    Copied from https://github.com/wkentaro/gdown

    Parse URLs especially for Google Drive links.
    drive_id: ID of file on Google Drive.
    is_download_link: Flag if it is download link of Google Drive.
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    drive_id = None
    if "id" in query:
        drive_ids = query["id"]
        if len(drive_ids) == 1:
            drive_id = drive_ids[0]
    else:
        patterns = [r"^/file/d/(.*?)/view$", r"^/presentation/d/(.*?)/edit$"]
        for pattern in patterns:
            match = re.match(pattern, parsed.path)
            if match:
                drive_id = match.groups()[0]
                break

    return drive_id


def get_url_from_gdrive_confirmation(contents: str) -> Optional[str]:
    """
    Copied from https://github.com/wkentaro/gdown
    """

    url = ""
    for line in contents.splitlines():
        m = re.search(r'href="(\/uc\?export=download[^"]+)', line)
        if m:
            url = "https://docs.google.com" + m.groups()[0]
            url = url.replace("&amp;", "&")
            break
        m = re.search('id="downloadForm" action="(.+?)"', line)
        if m:
            url = m.groups()[0]
            url = url.replace("&amp;", "&")
            break
        m = re.search('"downloadUrl":"([^"]+)', line)
        if m:
            url = m.groups()[0]
            url = url.replace("\\u003d", "=")
            url = url.replace("\\u0026", "&")
            break
        m = re.search('<p class="uc-error-subcaption">(.*)</p>', line)
        if m:
            error = m.groups()[0]
            raise RuntimeError(error)
    if not url:
        return None

    return url


def run_cmd_with_error(args: List[str]) -> None:
    result = subprocess.run(args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

    if result.returncode:
        print(error_text)
        print(f"The command `{' '.join(result.args)}` exited with exit code {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}")
        print("\nPress enter to continue")
        input()


def do_online_ffprobe(file: PreMediaContainer, helper: RequestHelper) -> Optional[Dict[str, Any]]:
    stream = helper.session.get_(file.download_url, stream=True)
    if stream is None:
        return None

    args = ["ffprobe", "-show_format", "-show_streams", "-of", "json", "-show_data_hash", "sha256", "-i", "-"]

    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        return None

    return cast(Dict[str, Any], json.loads(out.decode('utf-8')))


def do_ffprobe(filename: str) -> Optional[Dict[str, Any]]:
    # This function is copied and adapted from ffmpeg-python: https://github.com/kkroening/ffmpeg-python
    args = ["ffprobe", "-show_format", "-show_streams", "-of", "json", "-show_data_hash", "sha256", "-i", filename]

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
        logger.message("""Assertion failed: "codec_name" not in video_stream""")
        return None

    return bool(video_stream["codec_name"] == "hevc")


def check_pypi_for_version() -> Optional[Union[LegacyVersion, Version]]:
    # Inspired from https://pypi.org/project/pypi-search
    to_search = requests.get("https://pypi.org/project/isisdl/").text
    found_version = re.search("<h1 class=\"package-header__name\">\n *(.*)?\n *</h1>", to_search)

    if found_version is None:
        return None

    groups = found_version.groups()
    if groups is None or len(groups) != 1:
        return None

    return version.parse(groups[0].split()[1])


def check_github_for_version() -> Optional[Union[LegacyVersion, Version]]:
    if is_static:
        latest_release = requests.get("https://api.github.com/repos/Emily3403/isisdl/releases/latest").json()
        if "tag_name" not in latest_release:
            return None

        return version.parse(latest_release["tag_name"][1:])

    else:
        badge = requests.get("https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg").text
        if "passing" not in badge:
            return None

        res = requests.get("https://raw.githubusercontent.com/Emily3403/isisdl/main/src/isisdl/version.py")
        if not res.ok:
            return None

        found_version = re.match("__version__ = \"(.*)?\"", res.text)
        if found_version is None:
            return None

        return version.parse(found_version.group(1))


def install_latest_version() -> None:
    if is_first_time:
        return

    if config.update_policy is None:
        return

    # s = time.perf_counter()
    version_github = check_github_for_version()
    version_pypi = check_pypi_for_version()
    # print(f"{time.perf_counter() - s:.3f}")

    new_version = version_github if config.update_policy.endswith("github") else version_pypi

    if new_version is None:
        return

    if new_version <= version.parse(__version__):
        return

    print(f"\nThere is a new version of isisdl available: {new_version} (current: {__version__}).")

    if config.update_policy.startswith("notify"):
        return

    print("According to your update policy I will auto-install it.\n")
    if config.update_policy == "install_pip":
        ret = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "isisdl"])

    # TODO: test if this will work
    elif config.update_policy == "install_github":
        if is_static:
            with TemporaryDirectory() as tmp:
                assets = requests.get("https://api.github.com/repos/Emily3403/isisdl/releases/latest").json()["assets"]
                correct_name = "isisdl-windows.exe" if is_windows else "isisdl-linux.bin"
                for asset in assets:
                    if asset["name"] == correct_name:
                        break

                else:
                    print(f"{error_text} I cannot find the release for your platform.")
                    exit(1)

                new_file = requests.get(asset["browser_download_url"], stream=True)
                new_isisdl = os.path.join(tmp, correct_name)
                with open(new_isisdl, "wb") as f:
                    shutil.copyfileobj(new_file.raw, f)

                st = os.stat(new_isisdl)
                os.chmod(new_isisdl, st.st_mode | stat.S_IEXEC)
                os.replace(isisdl_executable, new_isisdl)

        else:
            ret = subprocess.call([sys.executable, "-m", "pip", "install", "git+https://github.com/Emily3403/isisdl"])



    else:
        assert False

    if ret == 0:
        print("\n\nSuccessfully updated!")
        exit(0)
    else:
        print("\n\nUpdating failed… why?")
        exit(ret)


def path(*args: str) -> str:
    return os.path.join(working_dir_location, *args)


def remove_systemd_timer() -> None:
    if not os.path.exists(timer_file_location):
        return

    run_cmd_with_error(["systemctl", "--user", "disable", "--now", "isisdl.timer"])
    run_cmd_with_error(["systemctl", "--user", "daemon-reload"])

    if os.path.exists(timer_file_location):
        os.remove(timer_file_location)

    if os.path.exists(service_file_location):
        os.remove(service_file_location)


def install_systemd_timer() -> None:
    import isisdl.bin.autorun
    with open(service_file_location, "w") as f:
        f.write(f"""# isisdl autorun service
# This file was autogenerated by `isisdl --init`.

[Unit]
Description=isisdl autorun
Wants=isisdl.timer

[Service]
Type=oneshot
ExecStart={isisdl_executable} {isisdl.bin.autorun.__file__}

[Install]
WantedBy=multi-user.target
""")

    with open(timer_file_location, "w") as f:
        f.write("""# isisdl autorun timer
# This file was autogenerated by the `isisdl-config` utility.

[Unit]
Description=isisdl
Wants=isisdl.service

[Timer]
Unit=isisdl.service
OnCalendar=hourly

[Install]
WantedBy=timers.target
""")

    run_cmd_with_error(["systemctl", "--user", "enable", "isisdl.timer"])
    run_cmd_with_error(["systemctl", "--user", "daemon-reload"])


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
    _pids_to_kill: List[int] = []

    def __init__(self) -> None:
        signal.signal(signal.SIGINT, OnKill.exit)
        signal.signal(signal.SIGABRT, OnKill.exit)
        signal.signal(signal.SIGTERM, OnKill.exit)
        signal.signal(signal.SIGILL, OnKill.exit)
        signal.signal(signal.SIGSEGV, OnKill.exit)

        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, OnKill.exit)
        else:
            signal.signal(signal.SIGBUS, OnKill.exit)
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
        if sig is None:
            OnKill.do_funcs()
            return

        if OnKill._already_killed:
            print("Alright, stay calm. I am skipping cleanup and exiting!")

            # Kill remaining processes
            for pid in OnKill._pids_to_kill:
                try:
                    if sys.platform == "win32":
                        os.kill(pid, signal.SIGABRT)
                    else:
                        os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

            os._exit(sig)

        OnKill._already_killed = True
        OnKill.do_funcs()
        os._exit(sig)

    @staticmethod
    def do_funcs() -> None:
        for _ in range(OnKill._funcs.qsize()):
            OnKill._funcs.get_nowait()[1]()

    @staticmethod
    def add_pid(pid: int) -> None:
        OnKill._pids_to_kill.append(pid)


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


def subscribe_to_all_courses() -> None:
    print("subscribe_to_all_courses is not implemented yet.")
    exit(1)


def unsubscribe_from_courses() -> None:
    print("unsubscribe_from_courses is not implemented yet.")
    exit(1)


class DataLogger(Thread):
    """
    What to log:

    System:
      × Hardware info
      ? Software info
      × isisdl version


    From ISIS:
      × Username
        How many courses
        How


    """

    def __init__(self) -> None:
        self.s = Session()
        self.generic_msg: Dict[str, Any] = {
            "username": User.sanitize_name(config.username),
            "OS": platform.system(),
            "OS_spec": distro.id(),
            "version": __version__,
            "time": int(time.time()),
            "is_first_time": is_first_time,
        }
        self.messages: Queue[Union[str, Dict[str, Any]]] = Queue()
        super().__init__(daemon=True)

    def run(self) -> None:
        while True:
            item = self.messages.get()
            self.s.post("http://static.246.42.12.49.clients.your-server.de/isisdl/", json=item)

    def message(self, msg: Union[str, Dict[str, Any]]) -> None:
        if config.telemetry_policy is False or is_testing:
            return

        deliver = self.generic_msg.copy()
        deliver["message"] = msg
        self.messages.put(deliver)

    def post(self, msg: Dict[str, Any]) -> None:
        if config.telemetry_policy is False or is_testing:
            return

        deliver = self.generic_msg.copy()
        deliver.update(msg)

        self.messages.put(deliver)

    def set_username(self, name: str) -> None:
        self.generic_msg["username"] = User.sanitize_name(name)


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
    def format_str(num: Optional[float]) -> str:
        if num is None:
            return "?"

        n, unit = HumanBytes.format(num)
        return f"{n:.2f} {unit}"

    @staticmethod
    def format_pad(num: Optional[float]) -> str:
        if num is None:
            return "   ?"

        n, unit = HumanBytes.format(num)
        return f"{f'{n:.2f}'.rjust(6)} {unit}"


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

colorama.init()
startup()
OnKill()

args = get_args()
database_helper = DatabaseHelper()
config = Config()

logger = DataLogger()
logger.start()
