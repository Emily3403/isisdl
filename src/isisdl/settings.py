# This settings file will get overwritten everytime a new version is installed.
# Don't overwrite any settings since you will have to manually edit this file everytime.
# Use the config file feature instead.

import logging.config
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
from typing import Any, DefaultDict, NoReturn

import psutil as psutil
from cryptography.hazmat.primitives.hashes import SHA3_512
from psutil._common import sdiskpart
from yaml import YAMLError, safe_load

import isisdl.frontend.autorun

# --- Options for this executable ---

# The directory where everything lives in.
working_dir_location = os.path.join(os.path.expanduser("~"), "isisdl")

intern_dir_location = ".intern"

database_file_location = os.path.join(intern_dir_location, "state.db")
temp_file_location = os.path.join(intern_dir_location, "temp_courses")
log_file_location = os.path.join(intern_dir_location, "isisdl.log")

datetime_str = "%Y-%m-%d %H:%M:%S"

# Settings for the lock
lock_file_location = os.path.join(intern_dir_location, "isisdl.lock")
enable_lock = False

# Options for the `--subscribe` feature
subscribed_courses_file_location = os.path.join(intern_dir_location, "subscribed_courses.json")
subscribe_num_courses_to_subscribe_to = -1
subscribe_num_threads = 32

# Courses that are locked. You probably don't want to subscribe to them since you can't unsub.
course_ids_cant_unsub_from = {
    25729, 25730, 25731, 25732, 24075, 24587, 24078, 23566, 24979, 11284, 28306, 26006, 27926, 26007, 26654, 26655, 23840, 28197, 24236, 21054, 27585, 28607, 21055, 25925,
    25924, 3793, 19671, 25578, 21610, 24813, 26736, 25458, 21875
}

# Settings for errors
error_directory_location = os.path.join(intern_dir_location, "errors")
error_text = "\033[1;91mError:\033[0m"


def error_exit(code: int, reason: str) -> NoReturn:
    print(f"{error_text} \"{reason}\"", flush=True, file=sys.stderr)
    os._exit(code)


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

# Note the absense of is_linux. It is implied by !is_windows and !is_macos.

# Check if the user has ffmpeg installed
has_ffmpeg = shutil.which("ffmpeg") is not None

# Check if being automatically run
is_autorun = sys.argv[0] == isisdl.frontend.autorun.__file__

# The location of the source code on disk
source_code_location = Path(isisdl.__file__).parent

# The path to the user-configuration directory.
if is_windows:
    if (_appdata_path := os.getenv("APPDATA")) is None:
        error_exit(4, "The %APPDATA% environment variable was not set ... why?")

    config_dir_location = os.path.join(_appdata_path, "isisdl")
else:
    config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "isisdl")

# The paths to the individual config files
config_file_location = os.path.join(config_dir_location, "config.yaml")
example_config_file_location = os.path.join(config_dir_location, "example.yaml")
export_config_file_location = os.path.join(config_dir_location, "export.yaml")

# Forbidden chars lookup-able dependent on OS.
# Reference: https://en.wikipedia.org/wiki/Filename#Reserved_characters_and_words

windows_forbidden_chars: set[str] = {"\\", "/", "?", "*", ":", "|", "\"", "<", ">", "\0"}
linux_forbidden_chars: set[str] = {"\0", "/"}
macos_forbidden_chars: set[str] = {"\0", "/"}

if is_windows:
    forbidden_chars = windows_forbidden_chars
elif is_macos:
    forbidden_chars = macos_forbidden_chars
else:
    forbidden_chars = linux_forbidden_chars

# Yes, this is a windows thing...
replace_dot_at_end_of_dir_name = is_windows

# Caching strategy

bad_url_cache_reeval_times_mul = 5
bad_url_cache_reeval_exp = 3
bad_url_cache_reeval_static_mul = 60

# Logging
logger_config = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "simple": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },

    "loggers": {
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "shila-lager": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

logging.config.dictConfig(logger_config)
logger = logging.getLogger("isisdl")

# -/- Options for this executable ---

# --- Database Configuration ---

database_url_location = os.path.join(config_dir_location, "database_url")
fallback_database_url = f"sqlite:///{os.path.join(working_dir_location, intern_dir_location, 'new_state.db')}"
# "postgresql+psycopg2://isisdl:isisdl@localhost:5432/isisdl"
# "mariadb+mariadbconnector://isisdl:isisdl@localhost:3306/isisdl_prod"
# f"sqlite:///{os.path.join(working_dir_location, intern_dir_location, 'new_state.db')}"

database_connect_args = {"check_same_thread": False}

# -/- Database Configuration


# --- Checksum options ---

# All checksums are calculated with this algorithm
checksum_algorithm = sha256

# The number of bytes sampled per iteration to compute a checksum
checksum_num_bytes = 1024 * 500

# Debugging option: after getting the entire content and after building the request cache do the following
# for file in content:
#  assert
#
# If the file size is not equal, but it is in a deviation of ±10%, the checksum will not be computed in order save some time.
perc_diff_for_checksum = 0.1  # 10% ± is allowed

# -/- Checksum options ---


# --- Password options ---

# TODO: Think about replacing SHA3 with Argon2id
password_hash_algorithm = SHA3_512
password_hash_iterations = 420_000
password_hash_length = 32

# The password used to encrypt if no password is provided
master_password = "qhoRmVBeH4km7vx84WK5pPm7KC7HAxKtQnewt2DwhDckKPSEo1q8uiTu4dK5soGn"

# The length of the salt stored in the database
random_salt_length = 64

# -/- Password options ---

# --- Status options ---

# The number of spaces a general status has.
status_progress_bar_resolution = 50

# The number of spaces for the downloads progress bar.
download_progress_bar_resolution = 10

# Minimum padding for courses / hostnames
course_pad_minimum_width = 20
hostname_pad_minimum_width = 17

# Chop off the last ↓ characters of the status message for a ...
status_chop_off = 3

# The status message is replaced every ↓ seconds  (on Windows™ cmd it is *very* slow)
status_time = 0.2 if not is_windows else 0.75

# -/- Status options ---


# --- Download options ---

# Chunks of this size are read and saved to file.
download_chunk_size = 2 ** 16

# Limit the size of the connection pool
connection_pool_limit = 16  # TODO: Test different values

# Number of threads to discover download urls.
discover_num_threads = 32

# Will fail a download if ISIS is not responding in
"""
for i in range(num_tries_download):
    download_timeout + download_timeout_multiplier ** (1.7 * i)
"""
num_tries_download = 2
download_base_timeout = 5
download_timeout_multiplier = 2

# If a download fails (`except Exception`) will wait ↓ and retry.
download_static_sleep_time = 3

# Moving average percent for the bandwidth calculation
bandwidth_mavg_perc = 0.2

bandwidth_download_files_mavg_perc = 0.6

# Should an invalid SSL (HTTPS) certificate be ignored?
download_ignore_bad_certificate = True

# -/- Download options ---


# --- Throttler options ---
# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.01

# Collect the amount of handed out tokens in the last ↓ secs for measuring the bandwidth
token_queue_bandwidths_save_for = 3

# When streaming, threads poll with this sleep time.
throttler_low_prio_sleep_time = 0.1

debug_cycle_time_deviation_allowed = 1.5

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

# The path to the systemd timer files. (Only supported on systemd-based linux)
systemd_dir_location = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
systemd_timer_file_location = os.path.join(systemd_dir_location, "isisdl.timer")
systemd_service_file_location = os.path.join(systemd_dir_location, "isisdl.service")

# -/- Linux only feature options ---

# --- Regex stuff ---

# Finds all urls in a given piece of text. Copied from https://gist.github.com/gruber/8891611
_url_finder = r"""(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%]))(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))"""  # noqa
url_finder = re.compile(_url_finder)

# Testing urls to be excluded. We know that they will not lead to a valid download.
testing_bad_urls: set[str] = {
    'https://tubcloud.tu-berlin.de/s/d8R6wdi2sTt5Jrj',
}

# In order to maintain a sense of order in the regex it is indented. Flake8 / PyCharm formatter do not seem to like that ...
# @formatter:off

# Regex to ignore a url depending on if there is some content
# TODO: Think about if I want mod/folder
isis_ignore = re.compile(
    r".*isis\.tu-berlin\.de/(?:"
        "mod/(?:"  # noqa:E131
            "forum|course|choicegroup|assign|feedback|choice|quiz|glossary|questionnaire|scorm"  # noqa:E131
            "|etherpadlite|lti|h5pactivity|page|data|ratingallocate|book|videoservice|lesson|wiki"
            "|organizer|registration|journal|workshop|survey|folder|bigbluebuttonbn"
        ")"
    "|"
        "availability/condition/shibboleth2fa|course|user|enrol"
    "|"
        "h5p"
    "|"
        "theme/image.php|local/isis"
    "|"
    ")/.*", re.IGNORECASE
)
# @formatter:on

regex_is_isis_document = re.compile(r".*isis\.tu-berlin\.de/(?:webservice/|)pluginfile\.php/.*", re.IGNORECASE)
regex_is_isis_video = re.compile(r".*isis\.tu-berlin\.de/videoservice/file.php/.*", re.IGNORECASE)

# @formatter:off
extern_ignore = re.compile(
    "(?:"
        "(?:https://)?(:?"  # noqa:E131
        # Full urls
        "berlin.de|tu-berlin.de|archive.org|b.sc|m.sc|nebula.stream"
        # Spam urls
        "|zmeu.us|69n.de|4-5.FM|6cin.de|6e.de|6e.de|6e.de|9.FM|10.FM|s.th|lin.de|flinga.fi|ICUnet.AG"
    "))"
        # Python files
        r"|\w+\.py"
    "|"
        # Match part of url's
        ".*(?:"
        "tu-berlin.zoom.us|moseskonto.tu-berlin.de|befragung.tu-berlin.de|tu-berlin.webex.com|git.tu-berlin.de|tubmeeting.tu-berlin.de"
        "|wikipedia.org|github.com|gitlab.tubit.tu-berlin.de|kahoot.it|www.python.org|www.anaconda.com|miro.com|teams.microsoft.com|cryptpad.fr"
        ").*",
    re.IGNORECASE
)
# @formatter:on


# -/- Regex stuff ---


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


# Parse the config file into the globals if on Posix
if not is_windows:
    data = parse_config_file()
    if data is not None:
        _globs = globals()
        for k, v in data.items():
            if k in _globs:
                _globs[k] = v


def check_online() -> bool:
    # Copied from https://stackoverflow.com/a/29854274
    conn = HTTPSConnection("isis.tu-berlin.de", timeout=5)
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

# Yes, changing behaviour when testing is evil. But I'm doing so in order to protect my `~/isisdl` directory.
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

    database_file_location = os.path.join(intern_dir_location, "state.db")
    log_file_location = os.path.join(intern_dir_location, "isisdl.log")
    lock_file_location = os.path.join(intern_dir_location, "isisdl.lock")
    subscribed_courses_file_location = os.path.join(intern_dir_location, "subscribed_courses.json")
    error_directory_location = os.path.join(intern_dir_location, ".errors")

    config_file_location = os.path.join(config_dir_location, "config.yaml")
    example_config_file_location = os.path.join(config_dir_location, "example.yaml")
    export_config_file_location = os.path.join(config_dir_location, "export.yaml")

    database_url_location = os.path.join(config_dir_location, "database_url")
    fallback_database_url = f"sqlite:///{os.path.join(working_dir_location, intern_dir_location, 'new_state.db')}"

    status_time = 1000000

# Environment variables are checked when authenticating
env_var_name_username = "ISISDL_USERNAME"
env_var_name_password = "ISISDL_PASSWORD"

# Should multithread be enabled? (Usually yes)
enable_multithread = True

global_vars = globals()
DEBUG_ASSERTS = bool(sys.flags.debug) or is_testing

testing_download_sizes = {
    1: 1_000_000_000,  # Video
    2: 2_500_000_000,  # Documents
    3: 1_000_000_000,  # Extern
    4: 0,  # Corrupted
}

# -/- Test Options ---

# --- Filesystem settings ---

# Filesystems also have limitations on their filenames.
# Reference: https://en.wikipedia.org/wiki/Comparison_of_file_systems#Limits

# Find out the `_path` of the mounted directory where the `working_dir_location` lives
_mount_partitions: dict[str, sdiskpart] = {part.mountpoint: part for part in psutil.disk_partitions()}

_working_path = Path(working_dir_location)
i = 0  # The loop can go on infinitely if ... (When does it happen?). Force stop it after 1000 iterations
while (_path := str(_working_path.resolve())) not in _mount_partitions and _working_path.resolve().parent != _working_path.resolve() and i < 1000:
    i += 1
    _working_path = _working_path.parent

# TODO: Make this more declarative with linux: ext2..4, windows: ...
# Also, expand the list with e.g. zfs, xfs, ...
_fs_forbidden_chars: dict[str, set[str]] = {
    "ext": linux_forbidden_chars,
    "ext2": linux_forbidden_chars,
    "ext3": linux_forbidden_chars,
    "ext4": linux_forbidden_chars,
    "btrfs": linux_forbidden_chars,

    "exfat": {chr(item) for item in range(0, 0x1f + 1)} | linux_forbidden_chars,

    "fat32": windows_forbidden_chars,
    "vfat": windows_forbidden_chars,
    "ntfs": windows_forbidden_chars,

    "hfs": macos_forbidden_chars,
    "hfsplus": macos_forbidden_chars,
    "apfs": macos_forbidden_chars,
}

# This is a constant to be overwritten for debugging purposes from the config file
force_filesystem: str | None = None

if _path in _mount_partitions:

    # If the path is mounted with windows names also forbid the windows chars
    if "windows_names" in _mount_partitions[_path].opts:
        forbidden_chars.update(windows_forbidden_chars)

    # Linux uses Filesystem in userspace and reports "fuseblk".
    if _mount_partitions[_path].fstype == "fuseblk":
        # TODO: Dynamic dependency of lsblk. What if the system does not have it?
        fstype = subprocess.check_output(f'lsblk -no fstype "$(findmnt --target "{_path}" -no SOURCE)"', shell=True).decode().strip()

    else:
        fstype = _mount_partitions[_path].fstype

    # Maybe apply the fstype overwrite
    if force_filesystem is not None:
        if force_filesystem not in _fs_forbidden_chars:
            error_exit(1, "You have forced a filesystem, but it is not in the expected:\n\n" + "\n".join(repr(item) for item in _fs_forbidden_chars))

        fstype = force_filesystem

    if fstype in _fs_forbidden_chars:
        forbidden_chars.update(_fs_forbidden_chars[fstype])
        if _fs_forbidden_chars[fstype] == windows_forbidden_chars:
            replace_dot_at_end_of_dir_name = True
    else:
        # TODO: Print a warning of some sort
        pass

else:
    print(f"{error_text} your filesystem is very wierd. Falling back on os-dependant fstype!")

    # This should not happen
    if is_windows:
        fstype = "ntfs"
    elif is_macos:
        fstype = "apfs"
    else:
        fstype = "ext4"

# -/- Filesystem settings ---
