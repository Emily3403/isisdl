# This settings file will get overwritten everytime a new version is installed.
# Don't overwrite any settings since you will have to manually edit this file everytime.
# Use the config file feature instead.

import os
import platform
import shutil
import sys
from collections import defaultdict
from hashlib import sha256
from http.client import HTTPSConnection
from linecache import getline
from typing import Any, DefaultDict

from cryptography.hazmat.primitives.hashes import SHA3_512
from yaml import safe_load, YAMLError

import isisdl.autorun

# The directory where everything lives in.

working_dir_location = os.path.join(os.path.expanduser("~"), "isisdl")

# The name of the SQLite Database
database_file_location = ".state.db"

current_database_version = 2

lock_file_location = ".lock"
enable_lock = True

error_directory_location = ".errors"

# --- Options for this executable ---
# Static settings
is_static = False

if is_static:
    isisdl_executable = os.path.realpath(sys.argv[0])
else:
    isisdl_executable = sys.executable

# A constant to detect if you are on Windows.
is_windows = platform.system() == "Windows"

# If the user has ffmpeg installed
has_ffmpeg = shutil.which("ffmpeg") is not None

# Check if being automatically run
is_autorun = sys.argv[0] == isisdl.autorun.__file__

# TODO: Add a setting for forcing characters to be ext4 / ntfs

error_text = "\033[1;91mError!\033[0m"

# -/- Options for this executable ---


# --- Checksum options ---

# All checksums are calculated with this algorithm
checksum_algorithm = sha256

# The number of bytes sampled per iteration to compute a checksum
checksum_num_bytes = 1024 * 4

# Skips $`checksum_base_skip` ^ i$ bytes per calculation → O(log(n)) time :O
checksum_base_skip = 2

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

# The number of spaces the first progress bar has
status_progress_bar_resolution = 50

# The number of spaces the second progress bar (for the downloads) has
download_progress_bar_resolution = 10

# Chop off the last ↓ characters of the status message for a ...
status_chop_off = 2

# The status message is replaced every ↓ seconds  (on Windows™ cmd it is *very* slow)
status_time = 0.1 if not is_windows else 0.75

# -/- Status options ---


# --- Download options ---

# Number of threads to discover video sizes
# TODO: Experiment with sizes
extern_discover_num_threads = 32

# Sets the chunk size for a download.
download_chunk_size = 2 ** 16

video_discover_download_size = 2 ** 8

# When ISIS is complaining that you are downloading too fast (Connection Aborted) ↓ s are waited.
sleep_time_for_isis = 3

# Will retry downloading an url ↓ times. If it fails, that MediaContainer will not get downloaded.
num_tries_download = 4

# Will fail a download if ISIS is not responding in
"""
for i in range(num_tries_download):
    download_timeout + download_timeout_multiplier ** (0.5 * i)
"""
download_timeout = 6
download_timeout_multiplier = 2

# -/- Download options ---


# --- Throttler options ---
# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.01

# Collect the amount of handed out tokens in the last ↓ secs for measuring the bandwidth
token_queue_download_refresh_rate = 3

# When streaming, threads poll. This will get changed.
throttler_low_prio_sleep_time = 0.1


# -/- Throttler options ---

# --- FFmpeg options ---
# Options for the `--compress` feature
ffmpeg_args = ["-crf", "28", "-c:v", "libx265", "-c:a", "copy", "-preset", "superfast"]

# TODO: Document this
compress_duration_for_to_low_efficiency = 0.5
compress_minimum_stdev = 0.5
compress_score_mavg_size = 5
compress_std_mavg_size = 5
compress_minimum_score = 1.6
compress_insta_kill_score = 1.9
compress_duration_for_insta_kill = 0

# -/- FFmpeg options ---

# Options for the `--subscribe` feature
subscribed_courses_file_location = "subscribed_courses.json"
subscribe_courses_range = (24005, 24010)
subscribe_num_threads = 32

# --- Linux only feature options ---

# The path to the user-configuration directory. Linux only feature
config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "isisdl")

# The paths to the individual config files
config_file_location = os.path.join(config_dir_location, "config.yaml")
example_config_file_location = os.path.join(config_dir_location, "example.yaml")
export_config_file_location = os.path.join(config_dir_location, "export.yaml")

# The path to the systemd timer files. (Only supported on systemd-based linux)
systemd_dir_location = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
timer_file_location = os.path.join(systemd_dir_location, "isisdl.timer")
service_file_location = os.path.join(systemd_dir_location, "isisdl.service")


# -/- Linux only feature options ---


# Now load any options the user may overwrite (Linux exclusive)
def parse_config_file() -> DefaultDict[str, Any]:
    try:
        with open(config_file_location) as f:
            _dat = safe_load(f)
            if _dat is None:
                return defaultdict(lambda: None)

            if not isinstance(_dat, dict):
                raise YAMLError("Wrong type: is not a mapping")
            return defaultdict(lambda: None, _dat)

    except OSError:
        pass

    # Exception handling inspired by https://stackoverflow.com/a/30407093
    except YAMLError as ex:
        # Unfortunately mypy doesn't support this well...
        if hasattr(ex, "problem_mark") and hasattr(ex, "context") and hasattr(ex, "problem") and hasattr(ex, "context_mark"):
            assert hasattr(ex, "problem_mark")
            if ex.context is None:  # type: ignore
                where = str(ex.problem_mark)[4:]  # type: ignore
                offending_line = getline(config_file_location, ex.problem_mark.line).strip("\n")  # type: ignore
            else:
                where = str(ex.context_mark)[4:]  # type: ignore
                offending_line = getline(config_file_location, ex.context_mark.line).strip("\n")  # type: ignore

            print(f"Malformed config file: {where.strip()}\n")
            if ex.context is not None:  # type: ignore
                print(f"Error: {ex.problem} {ex.context}")  # type: ignore

            print(f"Offending line: \"{offending_line}\"\n")
        else:
            print(f"{error_text} the config file contains an error / is malformed.")
            print(f"The file is located at `{config_file_location}`\n")
            print(f"Reason: {ex}\n")

        print("I will be ignoring the specified configuration.\n")

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
    1: 3_000_000_000,  # Video
    2: 1_000_000_000,  # Documents
    3: 1_000_000_000  # Extern
}

# </ Test Options >
