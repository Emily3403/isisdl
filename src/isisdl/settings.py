import os
import platform
import sys
from hashlib import sha256
from linecache import getline
from typing import Any, Dict, Optional, cast, Set

from yaml import safe_load, YAMLError

from cryptography.hazmat.primitives.hashes import SHA3_512

# This settings file will get overwritten everytime a new version is installed.
# Don't overwrite any settings since you will have to do it everytime.

# If you want to change behaviour that is not possible with the wizard please refer to the configuration docs.

# The directory where everything lives in.
working_dir_location = os.path.join(os.path.expanduser("~"), "isisdl_downloads")

# The name of the SQlite Database
# TODO: os.system( "attrib +h myFile.txt" )
database_file_location = ".state.db"

# The path to the user-configuration file. Linux only feature
config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "isisdl")

config_file_location = os.path.join(config_dir_location, "config.yaml")
example_config_file_location = os.path.join(config_dir_location, "example.yaml")

# The path to the systemd timer files. (Only supported on systemd-based linux)
timer_file_location = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user", "isisdl.timer")
service_file_location = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user", "isisdl.service")

lock_file_location = ".lock"
enable_lock = False

error_directory_location = ".errors"
error_file_location = "error in isisdl %Y-%m-%d %H-%M-%S"

# All checksums are calculated with this algorithm
checksum_algorithm = sha256

# The number of bytes sampled per iteration to compute a checksum
checksum_num_bytes = 1024 * 4

# Skips $`checksum_base_skip` ^ i$ bytes per calculation → O(log(n)) time :O
checksum_base_skip = 2

# Number of threads to use for the database requests when `isisdl-sync` is called
sync_database_num_threads = 32

# This is what Django recommends as of January 2021 (https://github.com/django/django/blob/main/django/contrib/auth/hashers.py#L274)
password_hash_algorithm = SHA3_512
password_hash_iterations = 390_000
password_hash_length = 32

# The password used to encrypt if no password is provided
master_password = "peanuts"

# The number of spaces the first progress bar has
first_progress_bar_resolution = 50

# The number of spaces the second progress bar (for the downloads) has
download_progress_bar_resolution = 10

# Chop off the last ↓ characters of the status message for a ...
status_chop_off = 2

# The status message is replaced every ↓ seconds
status_time = 0.25

# Environment variables are checked when authenticating
env_var_name_username = "ISISDL_USERNAME"
env_var_name_password = "ISISDL_PASSWORD"

# Set if the configuration wizard should clear the screen
config_clear_screen = True

enable_multithread = True

# Sets the chunk size for a download.
download_chunk_size = 2 ** 16

# When ISIS is complaining that you are downloading too fast (Connection Aborted) ↓ s are waited.
sleep_time_for_isis = 3

# Will retry downloading an url ↓ times. If it fails, that MediaContainer will not get downloaded.
num_tries_download = 4

# Will fail a download if ISIS is not responding in
# $`download_timeout` + `download_timeout_multiplier` ** (0.5 * i)$
download_timeout = 6
download_timeout_multiplier = 2

# A constant to detect if you are on Windows.
is_windows = platform.system() == "Windows"

# Check if running from cron
import isisdl.bin.autorun

is_autorun = sys.argv[0] == isisdl.bin.autorun.__file__

# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.1

# Collect the amount of handed out tokens in the last ↓ secs for measuring the bandwidth
token_queue_download_refresh_rate = 3


# Now load any options the user may overwrite (Linux exclusive)
def parse_config_file(allowed_values: Optional[Set[str]] = None) -> Dict[str, Any]:
    try:
        with open(config_file_location) as f:
            _dat = safe_load(f)
            if _dat is None:
                return {}
            dat: Dict[str, Any] = _dat


            if allowed_values is None:
                return dat

            bad_values = {}
            for k, v in dat.items():
                if k not in allowed_values:
                    bad_values[k] = v

            if bad_values:
                print(f"Unrecognized option{'s' if len(bad_values) > 1 else ''}:\n" + "\n".join(f"{k}: {v}" for k, v in bad_values.items()))

            return dat

    except OSError:
        pass

    # Exception handling inspired by https://stackoverflow.com/a/30407093
    except YAMLError as ex:
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
            print(f"Malformed config file at {config_file_location}.\nI can't diagnose the error.\n\n{ex}\n")

        print("I will be ignoring the specified configuration.\n")

    return {}


if not is_windows:
    data = parse_config_file()
    if data is not None:
        glob = globals()
        for k, v in data.items():
            if k in glob:
                glob[k] = v

# Check if the user is executing the library for the first time → .state.db should be missing
is_first_time = not os.path.exists(os.path.join(working_dir_location, database_file_location))

# Yes, changing behaviour when testing is evil. But I'm doing so in order to protect my `~/isisdl_downloads` directory.
is_testing = "pytest" in sys.modules
if is_testing:
    _working_dir_location = working_dir_location
    working_dir_location = os.path.join(os.path.expanduser("~"), "test_isisdl")
    _status_time = status_time
    status_time = 2
    download_timeout = 6

# This number represent seconds of video.
# (ISIS does not offer a better "size" api…)
testing_download_video_size = 3600 * 1

# Number of bytes downloaded for documents.
testing_download_documents_size = 1_000_000_000

# </ Test Options >
