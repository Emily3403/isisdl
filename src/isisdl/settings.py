# This settings file will get overwritten everytime a new version is installed.
# Don't overwrite any settings since you will have to manually edit this file everytime.
# Use the config file feature instead.

import os
import platform
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from hashlib import sha256
from http.client import HTTPSConnection
from pathlib import Path
from typing import Any, DefaultDict, Set, Dict, Optional

import psutil as psutil
from cryptography.hazmat.primitives.hashes import SHA3_512
from psutil._common import sdiskpart
from yaml import safe_load, YAMLError

import isisdl.autorun

# --- Options for this executable ---

# The directory where everything lives in.
working_dir_location = os.path.join(os.path.expanduser("~"), "isisdl")

# The name of the SQLite Database
database_file_location = ".state.db"

log_file_location = "isisdl.log"

datetime_str = "%Y-%m-%d %H:%M:%S"

# Settings for the lock
lock_file_location = ".lock"
enable_lock = True

# Options for the `--subscribe` feature
subscribed_courses_file_location = "subscribed_courses.json"
subscribe_num_courses_to_subscribe_to = -1
subscribe_num_threads = 32

# Courses that are locked. You probably don't want to subscribe to them since you can't unsub.
course_ids_cant_unsub_from = {
    25729, 25730, 25731, 25732, 24075, 24587, 24078, 23566, 24979, 11284, 28306, 26006, 27926, 26007, 26654, 26655, 23840, 28197, 24236, 21054, 27585, 28607, 21055, 25925,
    25924, 3793, 19671, 25578, 21610, 24813, 26736, 25458, 21875
}

# Settings for errors
error_directory_location = ".errors"
error_text = "\033[1;91mError:\033[0m"

# Static settings
is_static = False

if is_static:
    python_executable = os.path.realpath(sys.argv[0])
else:
    python_executable = sys.executable

# A constant to detect if you are on Windows.
is_windows = platform.system() == "Windows"

# A constant to detect if you are on macOS.
is_macos = platform.system() == "Darwin"

# If the user has ffmpeg installed
has_ffmpeg = shutil.which("ffmpeg") is not None

# Check if being automatically run
is_autorun = sys.argv[0] == isisdl.autorun.__file__

# Forbidden chars lookup-able by `is_windows`.
# Reference: https://en.wikipedia.org/wiki/Filename#Reserved_characters_and_words

windows_forbidden_chars: Set[str] = {"\\", "/", "?", "*", ":", "|", "\"", "<", ">", "\0"}
linux_forbidden_chars: Set[str] = {"\0", "/"}

forbidden_chars: Set[str] = windows_forbidden_chars if is_windows else linux_forbidden_chars

# Yes, this is a windows thing...
replace_dot_at_end_of_dir_name = is_windows

# -/- Options for this executable ---


# --- Checksum options ---

# All checksums are calculated with this algorithm
checksum_algorithm = sha256

# The number of bytes sampled per iteration to compute a checksum
checksum_num_bytes = 1024 * 500

# If the file size is not equal, but it is in this percentage the checksum will be computed in order to
perc_diff_for_checksum = 0.5

# -/- Checksum options ---


# --- Password options ---

# This is what Django recommends as of January 2021
password_hash_algorithm = SHA3_512
password_hash_iterations = 390_000
password_hash_length = 32

# The password used to encrypt if no password is provided
master_password = "eeb36e726e3ffec16da7798415bb4e531bf8a57fbe276fcc3fc6ea986cb02e9a"

# -/- Password options ---

# --- Status options ---

# The number of spaces a general status has.
status_progress_bar_resolution = 50

# The number of spaces for the downloads progress bar.
download_progress_bar_resolution = 10

# Chop off the last ↓ characters of the status message for a ...
status_chop_off = 3

# The status message is replaced every ↓ seconds  (on Windows™ cmd it is *very* slow)
status_time = 0.2 if not is_windows else 0.75

# -/- Status options ---


# --- Download options ---

# Chunks of this size are read and saved to file.
download_chunk_size = 2 ** 16

# Number of threads to discover download urls.
discover_num_threads = 32

# Will fail a download if ISIS is not responding in
"""
for i in range(num_tries_download):
    download_timeout + download_timeout_multiplier ** (0.5 * i)
"""
num_tries_download = 4
download_timeout = 10
download_timeout_multiplier = 2

# If a download fails (`except Exception`) will wait ↓ and retry.
download_static_sleep_time = 3

# Moving average percent for the bandwidth calculation
bandwidth_mavg_perc = 0.2

# -/- Download options ---


# --- Throttler options ---
# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.01

# Collect the amount of handed out tokens in the last ↓ secs for measuring the bandwidth
token_queue_download_refresh_rate = 3

# When streaming, threads poll with this sleep time.
throttler_low_prio_sleep_time = 0.1

# -/- Throttler options ---

# --- FFMpeg options ---

# Options for the ffmpeg executable
ffmpeg_args = ["-crf", "28", "-c:v", "libx265", "-c:a", "copy", "-preset", "superfast"]

# These are constants for stopping the compression, if the score is too low.
compress_duration_for_to_low_efficiency = 0.5
compress_minimum_stdev = 0.5
compress_score_mavg_size = 5
compress_std_mavg_size = 5
compress_minimum_score = 1.6
compress_insta_kill_score = 1.9
compress_duration_for_insta_kill = 0

# -/- FFMpeg options ---


# --- Linux only feature options ---

# The path to the user-configuration directory. Linux only feature
config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "isisdl")

# The paths to the individual config files
config_file_location = os.path.join(config_dir_location, "config.yaml")
example_config_file_location = os.path.join(config_dir_location, "example.yaml")
export_config_file_location = os.path.join(config_dir_location, "export.yaml")

# The path to the systemd timer files. (Only supported on systemd-based linux)
systemd_dir_location = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
systemd_timer_file_location = os.path.join(systemd_dir_location, "isisdl.timer")
systemd_service_file_location = os.path.join(systemd_dir_location, "isisdl.service")

# -/- Linux only feature options ---

# Finds all urls in a given piece of text. Copied from https://gist.github.com/gruber/8891611
_url_finder = r"""(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)/)(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))"""  # noqa
url_finder = re.compile(_url_finder)

# Testing urls to be excluded. We know that they will not lead to a valid download.
testing_bad_urls: Set[str] = {
    'https://tubcloud.tu-berlin.de/s/d8R6wdi2sTt5Jrj',
}

# Ignore mod/{whatever} isis urls
isis_ignore = re.compile(
    ".*isis.tu-berlin.de/mod/(?:"
    "forum|choicegroup|assign|feedback|choice|quiz|glossary|questionnaire|scorm"
    "|etherpadlite|lti|h5pactivity|page|data|ratingallocate|book|videoservice|lesson|wiki"
    "|organizer|registration|journal|workshop|survey"
    ")/.*"
)

extern_ignore = re.compile(
    ".*(?:"
    "tu-berlin.zoom.us|moseskonto.tu-berlin.de|befragung.tu-berlin.de|tu-berlin.webex.com|git.tu-berlin.de|tubmeeting.tu-berlin.de"
    "|wikipedia.org|github.com|gitlab.tubit.tu-berlin.de|kahoot.it|www.python.org|www.anaconda.com|miro.com"
    ").*"
)


def parse_config_file() -> DefaultDict[str, Any]:
    try:
        with open(config_file_location) as f:
            _dat = safe_load(f)
            if _dat is None:
                return defaultdict(lambda: None)

            if not isinstance(_dat, dict):
                raise YAMLError("Wrong type of data: no a mapping of values provided")

            return defaultdict(lambda: None, _dat)

    except OSError:
        pass

    # Exception handling inspired by https://stackoverflow.com/a/30407093
    except YAMLError as ex:
        print(f"{error_text} the config file is malformed.")
        print(f"The file is located at `{config_file_location}`\n\n")
        print(f"Reason: {ex}\n")

        os._exit(1)

    return defaultdict(lambda: None)


if not is_windows:
    data = parse_config_file()
    if data is not None:
        _globs = globals()
        for k, v in data.items():
            if k in _globs:
                _globs[k] = v


def check_online() -> bool:
    # Copied from https://stackoverflow.com/a/29854274
    conn = HTTPSConnection("8.8.8.8", timeout=5)
    try:
        conn.request("HEAD", "/")
        return True
    except Exception:
        return False
    finally:
        conn.close()


is_online = check_online()

# Check if the user is executing the library for the first time → .state.db should be missing
is_first_time = not os.path.exists(os.path.join(working_dir_location, database_file_location))

# --- Test options ---

# Yes, changing behaviour when testing is evil. But I'm doing so in order to protect my `~/isisdl_downloads` directory.
is_testing = "pytest" in sys.modules
if is_testing:
    _working_dir_location = working_dir_location
    _config_dir_location = config_dir_location
    _config_file_location = config_file_location
    _example_config_file_location = example_config_file_location
    _export_config_file_location = export_config_file_location
    _status_time = status_time

    working_dir_location = os.path.join(os.path.expanduser("~"), "testisisdl")
    config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "testisisdl")
    example_config_file_location = os.path.join(config_dir_location, "example.yaml")
    export_config_file_location = os.path.join(config_dir_location, "export.yaml")
    config_file_location = os.path.join(config_dir_location, "config.yaml")

    status_time = 1000000

# Environment variables are checked when authenticating
env_var_name_username = "ISISDL_USERNAME"
env_var_name_password = "ISISDL_PASSWORD"

# Should multithread be enabled? (Usually yes)
enable_multithread = True

global_vars = globals()

testing_download_sizes = {
    1: 1_000_000_000,  # Video
    2: 2_500_000_000,  # Documents
    3: 1_000_000_000,  # Extern
    4: 0,  # Corrupted
}

# -/- Test Options ---

# Filesystems also have limitations on their filenames.
# Reference: https://en.wikipedia.org/wiki/Comparison_of_file_systems#Limits

_mount_partitions: Dict[str, sdiskpart] = {part.mountpoint: part for part in psutil.disk_partitions()}
_working_path = Path(working_dir_location)
while (_path := str(_working_path.resolve())) not in _mount_partitions and _working_path.parent != _working_path:
    _working_path = _working_path.parent

force_filesystem: Optional[str] = None

_fs_forbidden_chars: Dict[str, Set[str]] = {
    "ext": linux_forbidden_chars,
    "ext2": linux_forbidden_chars,
    "ext3": linux_forbidden_chars,
    "ext4": linux_forbidden_chars,
    "btrfs": linux_forbidden_chars,

    "exfat": {chr(item) for item in range(0, 0x1f + 1)} | linux_forbidden_chars,

    "fat32": windows_forbidden_chars,
    "vfat": windows_forbidden_chars,
    "ntfs": windows_forbidden_chars,

    "hfs": set(),
    "hfsplus": set(),
}

if _path in _mount_partitions:
    if "windows_names" in _mount_partitions[_path].opts:
        forbidden_chars.update(windows_forbidden_chars)

    # Linux uses Filesystem in userspace and reports "fuseblk".
    if force_filesystem is not None:
        if force_filesystem not in _fs_forbidden_chars:
            print(f"{error_text} you have forced a filesystem, but it is not in the expected:\n\n" + "\n".join(repr(item) for item in _fs_forbidden_chars))
            os._exit(1)

        fstype = force_filesystem
    elif _mount_partitions[_path].fstype == "fuseblk":
        fstype = subprocess.check_output(f'lsblk -no fstype "$(findmnt --target "{_path}" -no SOURCE)"', shell=True).decode().strip()
        pass
    else:
        fstype = _mount_partitions[_path].fstype

    if fstype in _fs_forbidden_chars:
        forbidden_chars.update(_fs_forbidden_chars[fstype])
        if _fs_forbidden_chars[fstype] == windows_forbidden_chars:
            replace_dot_at_end_of_dir_name = True
