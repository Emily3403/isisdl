#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import enum
import json
import os
import platform
import random
import re
import shutil
import signal
import stat
import string
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import wraps
from itertools import repeat
from pathlib import Path
from queue import PriorityQueue, Queue, Full, Empty
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Callable, List, Tuple, Dict, Any, Set, cast, Iterable, NoReturn, TYPE_CHECKING, DefaultDict
from typing import Optional, Union
from urllib.parse import unquote, parse_qs, urlparse

import colorama
import distro as distro
import requests
from packaging import version
from packaging.version import Version, LegacyVersion
from requests import Session

from isisdl import settings
from isisdl.backend.database_helper import DatabaseHelper
from isisdl.settings import download_chunk_size, token_queue_download_refresh_rate, forbidden_chars, replace_dot_at_end_of_dir_name, force_filesystem, has_ffmpeg, fstype
from isisdl.settings import working_dir_location, is_windows, checksum_algorithm, checksum_num_bytes, example_config_file_location, config_dir_location, database_file_location, status_time, \
    discover_num_threads, status_progress_bar_resolution, download_progress_bar_resolution, config_file_location, is_first_time, is_autorun, parse_config_file, lock_file_location, \
    enable_lock, error_directory_location, systemd_dir_location, master_password, is_testing, systemd_timer_file_location, systemd_service_file_location, export_config_file_location, \
    python_executable, is_static, enable_multithread, subscribe_num_threads, subscribed_courses_file_location, error_text, token_queue_refresh_rate
from isisdl.version import __version__

if TYPE_CHECKING:
    from isisdl.backend.status import Status
    from isisdl.backend.request_helper import RequestHelper


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This program downloads and synchronizes all of your ISIS content.""")

    parser.add_argument("-t", "--max-num-threads", help="The maximum number of threads to spawn (for downloading files)\n ", type=int, default=3, metavar="{num}")
    parser.add_argument("-d", "--download-rate", help="Limits the download rate to {num} MiB/s\n ", type=float, default=None, metavar="{num}")

    operations = parser.add_mutually_exclusive_group()

    operations.add_argument("-v", "--version", help="Print the version number and exit", action="store_true")
    operations.add_argument("--init", help="Guides you through the initial configuration and setup process.", action="store_true")
    operations.add_argument("--config", help="Guides you through additional configuration which focuses on what to download from ISIS.", action="store_true")
    operations.add_argument("--sync", help="Do a full reset of the database, updating all file locations and urls.", action="store_true")
    operations.add_argument("--compress", help="Starts ffmpeg and will compress all downloaded videos.", action="store_true")
    operations.add_argument("--subscribe", help="Subscribes you to *all* ISIS courses publicly available.", action="store_true")
    operations.add_argument("--unsubscribe", help="Unsubscribes you from the courses you got subscribed by running `isisdl --subscribe`.", action="store_true")
    if not is_windows:
        operations.add_argument("--export-config", help=f"Exports the config to {export_config_file_location}.", action="store_true")

    operations.add_argument("--stream", help="Launches isisdl in streaming mode. Will watch for file accesses and download only those files.", action="store_true")
    operations.add_argument("--update", help="Checks if an update is available and installs it.", action="store_true")
    operations.add_argument("--delete-bad-urls", help="Deletes all urls deemed to be \"bad\" - meaning there is no content.", action="store_true")

    if is_testing:
        return parser.parse_known_args()[0]

    try:
        return parser.parse_args()
    except SystemExit as ex:
        os._exit(ex.code)


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
    throttle_rate: Optional[int]
    throttle_rate_autorun: Optional[int]
    update_policy: Optional[str]
    telemetry_policy: bool
    database_version: int
    absolute_path_filename: bool

    auto_subscribed_courses: Optional[List[int]]

    __slots__ = tuple(__annotations__)  # type: ignore

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
        "absolute_path_filename": False,
        "database_version": 2,

        "auto_subscribed_courses": None,
    }

    state: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {k: None for k in default_config}  # The state to consider after defaults, config files etc.
    _stored: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {}  # Values the user has actively stored in the config wizard (no config file)
    _backup: Dict[str, Union[bool, str, int, None, Dict[int, str]]] = {}  # Extra backup to maintain for tests
    _in_backup: bool = False

    def __init__(self, _prev_config: Optional[Dict[str, Any]] = None) -> None:
        config_file_data = parse_config_file()
        stored_config = database_helper.get_config()
        prev_config = _prev_config or {}

        # Filter out keys for settings
        for k, v in list(config_file_data.items()):
            if k in settings.__dict__:
                del config_file_data[k]

        # Verify config keys
        global_vars, default_keys = settings.global_vars, Config.default_config.keys()
        for k in list(config_file_data.keys()) + list(stored_config.keys()):
            if k not in global_vars and k not in default_keys:
                print(f"{error_text} the config file is malformed.")
                print(f"The file is located at `{config_file_location}`\n\n")
                print(f"Reason: Unrecognized key: {repr(k)}\n")
                os._exit(1)

        # Json only allows for keys to be strings (https://stackoverflow.com/a/8758771)
        # Set the keys manually back to ints, so we can work with them.
        for item in [config_file_data, stored_config]:
            if "renamed_courses" in item and item["renamed_courses"] is not None:
                assert isinstance(item["renamed_courses"], dict)
                item["renamed_courses"] = {int(k): v for k, v in item["renamed_courses"].items()}

        assert all(k in self.__slots__ for k in prev_config)

        self.state.update(Config.default_config)
        self.state.update(stored_config)
        self.state.update(prev_config)
        self.state.update(config_file_data)

        self._stored.update(stored_config)
        self.state["database_version"] = database_helper.get_database_version()

        if "database_version" not in self._stored:
            self._stored["database_version"] = self.default("database_version")

        if database_helper.get_database_version() == Config.default("database_version"):
            self.verify_state_types()

        for name in self.__slots__:
            super().__setattr__(name, Config.state[name])

    def __setattr__(self, key: str, value: Union[bool, str, int, None, Dict[int, str]]) -> None:
        super().__setattr__(key, value)
        if not self._in_backup:
            Config.state[key] = value
            Config._stored[key] = value
            database_helper.set_config(self._stored)

    def verify_state_types(self) -> None:
        # TODO: Use Config.__annotations__
        # Unfortunately we can't use the type annotations since they provide very little interface to python.
        def fail(attr: str, typ: Any, may_be_none: bool = False) -> None:
            if self.state[attr] is None and may_be_none:
                return

            if type(self.state[attr]) is not typ:
                print(f"{error_text} the config file is malformed.\n"
                      f"Reason: Expected type {typ} for key {repr(attr)}. Got {type(self.state[attr])}.\nBailing out!")
                os._exit(1)

        fail("password_encrypted", bool, True)
        fail("username", str, True)
        fail("password", str, True)
        fail("whitelist", list, True)
        fail("blacklist", list, True)
        fail("renamed_courses", dict, True)
        fail("make_subdirs", bool)
        fail("follow_links", bool)
        fail("download_videos", bool)
        fail("timer_enable", bool)
        fail("throttle_rate", int, True)
        fail("throttle_rate_autorun", int, True)
        fail("update_policy", str, True)
        fail("telemetry_policy", bool)
        fail("database_version", int)
        fail("absolute_path_filename", bool)

    @staticmethod
    def default(attr: str) -> Any:
        return Config.default_config[attr]

    @staticmethod
    def user(attr: str) -> Optional[Any]:
        return Config._stored.get(attr, None)

    def to_dict(self) -> Dict[str, Union[bool, str, int, None, Dict[int, str]]]:
        return {name: getattr(self, name) for name in self.__slots__}

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


def generate_config_str(
        working_dir_location: str, database_file_location: str, master_password: str, filename_replacing: bool, download_videos: bool, whitelist: Optional[List[int]], blacklist: Optional[List[int]],
        throttle_rate: Optional[int], throttle_rate_autorun: Optional[int], update_policy: Optional[str], telemetry_policy: bool, status_time: float, video_size_discover_num_threads: int,
        status_progress_bar_resolution: int, download_progress_bar_resolution: int, force_filesystem: Optional[str], make_subdirs: bool, follow_links: bool, absolute_path_filename: bool
) -> str:
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


# Should subdirectories be created?
# Possible values {{"true", "false"}}
make_subdirs: {encode_yaml(make_subdirs)}


# Should external links be followed?
# Possible values {{"true", "false"}}
follow_links: {encode_yaml(follow_links)}


# Should the displayed name be absolute or just the name?
# Possible values {{"true", "false"}}
absolute_path_filename: {encode_yaml(absolute_path_filename)}


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


# Force a filesystem
# Possible values {{null, ext, ext2, ext3, ext4, btrfs, exfat, fat32, vfat, ntfs, hfs, hfsplus}}
force_filesystem: {force_filesystem}


# Number of threads to use when discovering video file sizes (ISIS does not offer an API).
# Possible values {{any integer > 0}}
video_size_discover_num_threads: {video_size_discover_num_threads}


# The resolution of any ordinary status has.
# Possible values {{any integer > 0}}
status_progress_bar_resolution: {status_progress_bar_resolution}

# The resolution of the download progress bar.
# Possible values {{any integer > 0}}
download_progress_bar_resolution: {download_progress_bar_resolution}
"""


def generate_default_config_str() -> str:
    return generate_config_str(
        working_dir_location, database_file_location, master_password, Config.default("filename_replacing"), Config.default("download_videos"), Config.default("whitelist"),
        Config.default("blacklist"), Config.default("throttle_rate"), Config.default("throttle_rate_autorun"), Config.default("update_policy"), Config.default("telemetry_policy"), status_time,
        discover_num_threads, status_progress_bar_resolution, download_progress_bar_resolution, force_filesystem, Config.default("make_subdirs"), Config.default("follow_links"),
        Config.default("absolute_path_filename")
    )


def generate_current_config_str() -> str:
    return generate_config_str(
        working_dir_location, database_file_location, master_password, config.filename_replacing, config.download_videos, config.whitelist, config.blacklist, config.throttle_rate,
        config.throttle_rate_autorun, config.update_policy, config.telemetry_policy, status_time, discover_num_threads, status_progress_bar_resolution, download_progress_bar_resolution,
        force_filesystem, config.make_subdirs, config.follow_links, config.absolute_path_filename
    )


def export_config() -> None:
    with open(export_config_file_location, "w") as f:
        f.write(generate_current_config_str())


def startup() -> None:
    os.makedirs(path(), exist_ok=True)
    if os.path.exists(path(error_directory_location)) and os.listdir(path(error_directory_location)) == []:
        os.rmdir(path(error_directory_location))

    if os.path.exists(python_executable + ".old"):
        os.unlink(python_executable + ".old")

    if not is_windows:
        os.makedirs(path(config_dir_location), exist_ok=True)
        os.makedirs(systemd_dir_location, exist_ok=True)

        default_config_str = generate_default_config_str()

        with open(example_config_file_location, "w") as f:
            f.write(default_config_str)

        if not os.path.exists(config_file_location):
            with open(config_file_location, "w") as f:
                f.write(f"# You probably want to start by copying {example_config_file_location} and adapting it.\n")


def clear() -> None:
    if is_windows:
        os.system('cls')
    else:
        os.system('clear')


def migrate_database() -> bool:
    print(f"""
I have detected a breaking change in the database.
In order to account for these changes, I will have to delete the database,
make a few changes to local files and rediscover all the files.

If something goes wrong, simply delete the directory
`{path()}`
and everything will get downloaded as usual.

Please confirm that this is okay. [y/n]""")
    choice = get_input({"y", "n"})
    if choice == "n":
        print("Alright, I am not doing any changes.")
        return False

    from isisdl.backend.crypt import get_credentials
    from isisdl.backend.request_helper import RequestHelper
    global config
    helper = RequestHelper(get_credentials(["peanuts"]))

    def migrate_1_to_2() -> None:
        course_name_counts: DefaultDict[str, int] = defaultdict(int)
        for course in helper._courses:
            course_name_counts[course.displayname] += 1

        for _course, num in course_name_counts.items():
            if num > 1:
                try:
                    shutil.rmtree(path(_course))
                except OSError:
                    pass

        downloaded_courses = set(os.listdir(path()))
        for course in helper._courses:
            if course.name == course.displayname:
                continue

            if course.displayname in downloaded_courses:
                if os.path.exists(path(course.name)):
                    shutil.rmtree(path(course.name))

                try:
                    os.rename(path(course.displayname), path(course.name))
                except OSError as ex:
                    generate_error_message(ex)

        config.database_version = 2

    while database_helper.get_database_version() < config.default("database_version"):
        eval(f"migrate_{database_helper.get_database_version()}_to_{database_helper.get_database_version() + 1}()")

    os.unlink(path(database_file_location))

    print("\nSuccessfully migrated.\nPlease restart me and I will guide you through the new configuration!")

    return True


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
            return None

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


def do_ffprobe(file: Path) -> Optional[Dict[str, Any]]:
    # This function is copied and adapted from ffmpeg-python: https://github.com/kkroening/ffmpeg-python
    args = ["ffprobe", "-show_format", "-show_streams", "-of", "json", "-show_data_hash", "sha256", "-i", str(file)]

    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        return None

    return cast(Dict[str, Any], json.loads(out.decode('utf-8')))


def is_h265(file: Path) -> Optional[bool]:
    probe = do_ffprobe(file)
    if probe is None:
        return None

    video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
    if video_stream is None:
        return None

    if "codec_name" not in video_stream:
        logger.assert_fail('"codec_name" not in video_stream')
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

    if is_static and "github" not in config.update_policy:
        print(f'''{error_text} the update policy specified is {config.update_policy!r}.
Allowed values are {{"notify github", "install github"}}.

Please run `isisdl --init` to resolve this issue!
''')
        os._exit(1)

    version_github = check_github_for_version()
    version_pypi = check_pypi_for_version()

    new_version = version_github if config.update_policy.endswith("github") or is_static else version_pypi

    if new_version is None:
        return

    if new_version <= version.parse(__version__):
        return

    print(f"\nThere is a new version of isisdl available: {new_version} (current: {__version__}).")

    if config.update_policy.startswith("notify") and not args.update:
        return
    elif config.update_policy.startswith("install"):
        print("According to your update policy I will auto-install it.\n")

    if "pip" in config.update_policy:
        ret = subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "isisdl"])

    elif "github" in config.update_policy and is_static is False:
        ret = subprocess.call([sys.executable, "-m", "pip", "install", "git+https://github.com/Emily3403/isisdl"])

    elif "github" in config.update_policy and is_static:
        with TemporaryDirectory() as tmp:
            assets = requests.get("https://api.github.com/repos/Emily3403/isisdl/releases/latest").json()["assets"]
            correct_name = "isisdl-windows.exe" if is_windows else "isisdl-linux.bin"
            for asset in assets:
                if asset["name"] == correct_name:
                    break

            else:
                print(f"{error_text} I cannot find the release for your platform.")
                sys.exit(1)

            new_file = requests.get(asset["browser_download_url"], stream=True)
            new_isisdl = os.path.join(tmp, "tmp." + correct_name)
            with open(new_isisdl, "wb") as f:
                shutil.copyfileobj(new_file.raw, f)

            os.rename(python_executable, python_executable + ".old")
            shutil.copyfile(new_isisdl, python_executable)

            st = os.stat(python_executable)
            os.chmod(python_executable, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            ret = 0

    else:
        assert False

    if ret == 0:
        print("\n\nSuccessfully updated!")
        sys.exit(0)
    else:
        print("\n\nUpdating failed… why?")
        sys.exit(ret)


def path(*args: str) -> Path:
    return Path(working_dir_location, *args)


def remove_systemd_timer() -> None:
    if not os.path.exists(systemd_timer_file_location):
        return

    run_cmd_with_error(["systemctl", "--user", "disable", "--now", "isisdl.timer"])
    run_cmd_with_error(["systemctl", "--user", "daemon-reload"])

    if os.path.exists(systemd_timer_file_location):
        os.remove(systemd_timer_file_location)

    if os.path.exists(systemd_service_file_location):
        os.remove(systemd_service_file_location)


def install_systemd_timer() -> None:
    import isisdl.autorun
    with open(systemd_service_file_location, "w") as f:
        f.write(f"""# isisdl autorun service
# This file was autogenerated by `isisdl --init`.

[Unit]
Description=isisdl autorun
Wants=isisdl.timer

[Service]
Type=oneshot
ExecStart={python_executable} {isisdl.autorun.__file__}

[Install]
WantedBy=multi-user.target
""")

    with open(systemd_timer_file_location, "w") as f:
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


def sanitize_name(name: str, is_dir: bool) -> str:
    # Remove unnecessary whitespace
    name = name.strip()
    name = unquote(name)

    # First replace umlaute
    for a, b in {"ä": "a", "ö": "o", "ü": "u"}.items():
        name = name.replace(a, b)
        name = name.replace(a.upper(), b.upper())

    # Now start to add chars that don't fit.
    char_string = ""

    # Now replace any remaining funny symbols with a `?`
    name = name.encode("ascii", errors="replace").decode()

    if config.filename_replacing:
        char_string += r"""!"#$%&'()*+,/:;<=>?@[\]^`{|}~"""
        name = name.translate(str.maketrans(char_string, "\0" * len(char_string)))

    # This is probably a suboptimal solution, but it works…
    str_list = list(name)
    final = []

    if config.filename_replacing:
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
    else:
        final = str_list

    # Folder names cannot end with a period in Windows ...
    while replace_dot_at_end_of_dir_name and is_dir and final and (final[-1] == "." or final[-1] == " "):
        final.pop()

    final_str = "".join(item for item in final if item not in forbidden_chars)

    # All supported filesystems have a limit of 255 bytes for the filename. Enforce it.
    return final_str.encode()[:255].decode()


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
        os._exit(0)

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


def acquire_file_lock_or_exit() -> None:
    if acquire_file_lock():
        print(f"I could not acquire the lock file: `{path(lock_file_location)}`\nIf you are certain that no other instance of `isisdl` is running, you may delete it.")

        if is_autorun:
            os._exit(1)

        print("\nIf you want, I can also delete it for you: [y/n]")
        choice = get_input({"y", "n"})
        if choice == "y":
            os.remove(path(lock_file_location))
            acquire_file_lock()
        else:
            print("Exiting ...")
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


class User:
    username: str
    password: str

    __slots__ = tuple(__annotations__)  # type: ignore

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    @staticmethod
    def sanitize_name(name: Optional[str]) -> Optional[str]:
        if name is None:
            return None

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
    alg = checksum_algorithm()

    alg.update(str(os.path.getsize(filename)).encode())
    with open(filename, "rb") as f:
        i = 1
        while True:
            # f.seek(3 ** i, 1)  # This enables O(log(n)) time.
            data = f.read(checksum_num_bytes)

            if not data:
                break

            alg.update(data)
            i += 1

    return alg.hexdigest()


def subscribe_to_all_courses() -> None:
    from isisdl.backend.request_helper import RequestHelper
    from isisdl.backend.crypt import get_credentials
    from isisdl.backend.status import Status

    # TODO: Precalculate a list of courses that can be subscribed to.

    print("How many courses do you want to subscribe to? (-1 for all)\n(Subscribing may fail, about 1/4 of the courses work.)\n\n")
    while True:
        try:
            choice = int(input())
            break

        except ValueError as exc:
            print(f"{error_text} Parsing the integer failed.\nReason: {exc}")

    helper = RequestHelper(get_credentials())
    possible = list(range(0, 30000))
    random.shuffle(possible)

    possible = possible[:choice]

    def enrol_course(id: int, status: Status) -> Optional[int]:
        res = helper.post_REST("enrol_self_enrol_user", {"courseid": id})
        status.done()
        if res is None or "status" not in res or res["status"] is False:
            return None

        return id

    with Status("Subscribing to courses", len(possible)) as status:
        if enable_multithread:
            with ThreadPoolExecutor(subscribe_num_threads) as ex:
                ids = list(ex.map(enrol_course, possible, repeat(status)))
        else:
            ids = [enrol_course(i, status) for i in possible]

    _new_ids = [item for item in ids if item is not None]

    try:
        with open(path(subscribed_courses_file_location)) as f:
            prev_ids = json.load(f)
    except OSError:
        prev_ids = []

    new_ids = list({id for id in _new_ids + prev_ids})

    if config.auto_subscribed_courses is None:
        config.auto_subscribed_courses = new_ids
    else:
        config.auto_subscribed_courses = list(set(config.auto_subscribed_courses + new_ids))

    with open(path(subscribed_courses_file_location), "w") as f:
        json.dump(config.auto_subscribed_courses, f)

    print(f"Subscribed to {len(_new_ids)} new courses.\n\nI have also written this information to `{path(subscribed_courses_file_location)}`.\n"
          f"Make sure to backup this file. If the database is deleted and you don't have this file,\nyou will not be able to unsubscribe from the courses.")


def check_can_unsub_from_course(course_id: int, status: Status, helper: RequestHelper) -> Optional[Tuple[int, bool]]:
    res = helper.session.get_("https://isis.tu-berlin.de/course/view.php", params={"id": course_id})
    if res is None:
        return None

    status.done()
    return course_id, "https://isis.tu-berlin.de/enrol/self/unenrolself.php" in res.text


def unsubscribe_from_courses() -> None:
    if config.auto_subscribed_courses is None:
        print("I could not find the courses I have subscribed to in the database.")
        if path(subscribed_courses_file_location).exists():
            print("I have found the an export of the courses I have subscribed to.\n\nDo you want me to use that instead? [y/n]\n")
            choice = get_input({"y", "n"})
            if choice == "n":
                return

            with path(subscribed_courses_file_location).open() as f:
                auto_subscribed_courses = json.load(f)

    else:
        auto_subscribed_courses = config.auto_subscribed_courses

    from isisdl.backend.request_helper import RequestHelper
    from isisdl.backend.crypt import get_credentials
    from isisdl.backend.status import Status, RequestHelperStatus

    with RequestHelperStatus() as status:
        helper = RequestHelper(get_credentials(), status)

    # Filter the courses
    prev_courses = set([item.course_id for item in helper.courses])
    auto_subscribed_courses = [item for item in auto_subscribed_courses if item in prev_courses]

    # dont_unsub = {26113, 27905, 24337, 23461, 28218, 24382, 24000, 26566, 26956, 19030, 23793, 28069, 28694}
    # with Status("Checking for unsub", len(prev_courses)) as status:
    #     with ThreadPoolExecutor(64) as ex:
    #         res = list(ex.map(check_can_unsub_from_course, prev_courses, repeat(status), repeat(helper)))
    #
    # print(f"Can't unsub from {sum(1 for item in res if item is not None and item[1] is False)}:\n{{\n    " + ", ".join(str(item[0]) for item in res if item is not None and item[1] is False) + "\n}")
    # print(f"Can unsub {sum(1 for item in res if item is not None and item[1] and item[0] not in dont_unsub)}")

    # I would like to do the subscription with the API method `enrol_self_enrol_user`, but it doesn't give enough information
    def unsubscribe_course(course_id: int, status: Status) -> bool:
        _possible_ids = helper.post_REST("enrol_self_enrol_user", {"courseid": course_id})
        if _possible_ids is None or "warnings" not in _possible_ids:
            return False

        possible_ids: List[Dict[str, Any]] = _possible_ids["warnings"]

        res = None
        for id in possible_ids:
            if id["warningcode"] != "1":
                continue

            res = helper.session.post_("https://isis.tu-berlin.de/enrol/self/unenrolself.php", data={"enrolid": id["itemid"], "confirm": 1, "sesskey": helper.session.key}, allow_redirects=False)
        status.done()

        return res is None

    with Status("Unsubscribing from courses", len(auto_subscribed_courses)) as status:
        if enable_multithread:
            with ThreadPoolExecutor(subscribe_num_threads) as ex:
                fails = list(ex.map(unsubscribe_course, auto_subscribed_courses, repeat(status)))

        else:
            fails = [unsubscribe_course(item, status) for item in auto_subscribed_courses]

    now_courses = [item for fail, item in zip(fails, auto_subscribed_courses) if fail]
    print(f"Successfully unsubscribed from {len(auto_subscribed_courses) - len(now_courses)} courses.")
    if now_courses:
        print("There are still courses left. Please restart me!")
    config.auto_subscribed_courses = now_courses or None


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

    s: Session
    messages: Queue[Union[str, Dict[str, Any]]]
    done: Queue[None]  # Used to communicate
    generic_msg: Dict[str, Any]

    __slots__ = tuple(__annotations__)  # type: ignore

    def __init__(self) -> None:
        self.s = Session()
        self.messages = Queue()
        self.done = Queue()
        self.generic_msg = {
            "username": User.sanitize_name(config.username),
            "OS": platform.system(),
            "OS_spec": distro.id(),
            "version": __version__,
            "database_version": Config.default("database_version"),
            "has_ffmpeg": has_ffmpeg,
            "forbidden_chars": list(forbidden_chars),
            "fstype": fstype,
            "is_static": is_static,
            "time": int(time.time()),
            "is_first_time": is_first_time,
        }

        super().__init__(daemon=True)
        self.start()

    def run(self) -> None:
        try:
            while True:
                item = self.messages.get()
                self.s.post("http://49.12.42.246/isisdl/", json=item)
                self.done.put(None)
        except Exception as ex:
            generate_error_message(ex)

    def message(self, msg: Union[str, Dict[str, Any]]) -> None:
        if config.telemetry_policy is False or is_testing:
            return

        deliver = self.generic_msg.copy()
        deliver["message"] = msg
        self.messages.put(deliver)

    def assert_fail(self, msg: str) -> None:
        self.message(f"Assertion failed: {msg}")

    def post(self, msg: Dict[str, Any]) -> None:
        if config.telemetry_policy is False or is_testing:
            return

        deliver = self.generic_msg.copy()
        deliver.update(msg)

        self.messages.put(deliver)

    def set_username(self, name: str) -> None:
        self.generic_msg["username"] = User.sanitize_name(name)


# Represents a granted token. A download may only download as much as defined in num_bytes.
class Token:
    num_bytes: int = download_chunk_size


# TODO: When streaming a file the download rate will not be limited.
class DownloadThrottler(Thread):
    """
    This class acts in a way that the download speed is capped at a certain maximum speed.
    It does so by handing out tokens, which are limited.
    With every token you may download a number of bytes.
    """
    download_queue: Queue[Token]
    used_tokens: Queue[Token]
    download_rate: int
    refresh_rate: float

    __slots__ = tuple(__annotations__)  # type: ignore

    token = Token()
    timestamps: List[float] = []
    _streaming_loc: Optional[Path] = None

    def __init__(self) -> None:
        self.download_queue, self.used_tokens = Queue(), Queue()
        self.download_rate = args.download_rate or config.throttle_rate or -1
        self.refresh_rate = token_queue_refresh_rate

        # Maybe the token_queue_refresh_rate is too small and there will be no tokens.
        # Check if that will be the case and adapt it accordingly.
        if self.download_rate != -1:
            while self.max_tokens() < args.max_num_threads:
                self.refresh_rate *= 2

        for _ in range(self.max_tokens()):
            self.download_queue.put(Token())

        super().__init__(daemon=True)
        self.start()

    def run(self) -> None:
        while True:
            start = time.perf_counter()

            # Clear old timestamps
            while self.timestamps:
                if self.timestamps[0] < start - token_queue_download_refresh_rate:
                    self.timestamps.pop(0)
                else:
                    break

            # If a download limit is imposed hand out new tokens
            if self.download_rate != -1 and self._streaming_loc is None:
                try:
                    for _ in range(self.max_tokens()):
                        self.download_queue.put(self.used_tokens.get(block=False))

                except (Full, Empty):
                    pass

            # Finally, compute how much time we've spent doing this stuff and sleep the remainder.
            time.sleep(max(self.refresh_rate - (time.perf_counter() - start), 0))

    @property
    def bandwidth_used(self) -> float:
        """
        Returns the bandwidth used in bytes / second
        """
        return float(len(self.timestamps) * download_chunk_size / token_queue_download_refresh_rate)

    def get(self, location: Path) -> Token:
        try:
            if self.download_rate == -1 or location == self._streaming_loc:
                return self.token

            token = self.download_queue.get()
            self.used_tokens.put(token)

            return token

        finally:
            # Only append it at exit
            self.timestamps.append(time.perf_counter())

    def start_stream(self, location: Path) -> None:
        self._streaming_loc = location

    def end_stream(self) -> None:
        self._streaming_loc = None

    def max_tokens(self) -> int:
        if self.download_rate == -1 or self.download_rate is None:
            return 1

        return int((self.download_rate * 1024 ** 2) // download_chunk_size * self.refresh_rate) or 1


class MediaType(enum.Enum):
    document = 1
    extern = 2
    video = 3
    corrupted = 4

    @property
    def dir_name(self) -> str:
        if self == MediaType.video:
            return "Videos"
        if self == MediaType.extern:
            return "Extern"

        return ""

    def __str__(self) -> str:
        if self == MediaType.video:
            return "video"
        elif self == MediaType.document:
            return "document"
        elif self == MediaType.extern:
            return "external link"
        elif self == MediaType.corrupted:
            return "corrupted file"

        assert False

    @staticmethod
    def list_dirs() -> Iterable[str]:
        return "Videos", "Extern"


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


def generate_error_message(ex: Exception) -> NoReturn:
    if is_testing:
        raise ex

    print("\nI have encountered the following Exception. I'm sorry this happened 😔\n")
    print(traceback.format_exc())

    file_location = path(error_directory_location, f"{int(datetime.now().timestamp())}.txt")
    print(f"I have logged this error to the file\n{file_location}")

    os.makedirs(path(error_directory_location), exist_ok=True)
    with open(file_location, "w") as f:
        f.write(traceback.format_exc())

    os._exit(1)


# Don't create startup files
if is_first_time:
    if is_autorun:
        os._exit(1)

colorama.init()
startup()
OnKill()

args = get_args()
database_helper = DatabaseHelper()
bad_urls = database_helper.get_bad_urls()
config = Config()
created_lock_file = False

logger = DataLogger()
