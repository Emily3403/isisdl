import datetime
import os
import platform
import sys
from dataclasses import dataclass
from hashlib import sha256

from cryptography.hazmat.primitives.hashes import SHA3_512

# In this file you will find various constants that dictate how isis_dl works.
# First up there are things that you may want to change.
# In the second part you should only change stuff if you know what you are doing.

# < Directory options >

# The directory where everything lives in.
# Note: If you want to expand your "~" use `os.path.expanduser("~")`. Otherwise a Directory with the literal `~` will be created in the current working directory.
working_dir_location = os.path.join(os.path.expanduser("~"), "isis_dl_downloads")

# The directory where files get saved to
download_dir_location = "Courses"

# The directory for intern stuff such as passwords
intern_dir_location = ".intern"

# The directory for unpacked archives such as .zip and .tar.gz
unpacked_archive_dir_location = "UnpackedArchives"
unpacked_archive_suffix = ".unpacked"

# Will create a symlink in the working_dir.
settings_file_location = os.path.join(intern_dir_location, "settings.py")

# Logs
log_dir_location = os.path.join(intern_dir_location, "logs")
log_file_location = os.path.join(log_dir_location, "log" + datetime.datetime.now().strftime("-%Y-%m-%d-%H:%M:%S") + ".log")

whitelist_file_name_location = os.path.join(intern_dir_location, "whitelist.txt")
blacklist_file_name_location = os.path.join(intern_dir_location, "blacklist.txt")
course_name_to_id_file_location = os.path.join(intern_dir_location, "id_file.json")

# </ Directory options >

# < Checksums >

# Checksums are dumped into this file on a per-course basis.
checksum_file = ".checksums.json"
checksum_algorithm = sha256


@dataclass
class ExtensionNumBytes:
    """a docstring"""
    num_bytes_per_point: int = 64

    skip_header: int = 0
    skip_footer: int = 0
    num_data_points: int = 3


# The number of bytes which get considered for a checksum. See the according documentation in the wiki (currently non existent D:).
checksum_num_bytes = {
    ".zip": ExtensionNumBytes(skip_header=512),

    None: ExtensionNumBytes(),
}

# A special case: The server is ignoring the Range parameter that is given. In that case read the first ↓ bytes and calculate the checksum based on that.
checksum_range_parameter_ignored = 512

# </ Checksums >


# < Password / Cryptography options >

password_dir = os.path.join(intern_dir_location, "Passwords")
clear_password_file = os.path.join(password_dir, ".pass.clean")
encrypted_password_file = os.path.join(password_dir, ".pass.encrypted")

already_prompted_file = os.path.join(password_dir, ".pass.prompted")

# Beware: Changing any of these options means loosing compatibility with the old password file.
hash_iterations = 320_000  # This is what Django recommends as of January 2021 (https://github.com/django/django/blob/main/django/contrib/auth/hashers.py)
hash_algorithm = SHA3_512()
hash_length = 32

# < Password / Cryptography options >

# < Miscellaneous options >

# The number of places the progress bar has.
progress_bar_resolution = 16

# The number of sessions to open with Shibboleth.
num_sessions = 6

# It is possible to specify credentials using environment variables.
# Note that `env_var_name_username` and `env_var_name_password` take precedence over `env_var_name_encrypted_password`

# If you want to use username and password set these variables accordingly.
env_var_name_username = "ISIS_DL_USERNAME"
env_var_name_password = "ISIS_DL_PASSWORD"

# If you want to use the encrypted file to store your credentials then specify your password with the environment variable.
env_var_name_encrypted_password = "ISIS_DL_ENC_PASSWORD"

# </ Miscellaneous options >


# Begin second part.


# < Miscellaneous options >

# Enables debug features.
debug_mode = False

enable_multithread = True

# Will disable the status.
print_status = True
log_clear_screen = True  # Triggers a `clear` command every time before printing.
status_time = 0.5  # The refresh time.

# Sets the chunk size.
download_chunk_size = 2 ** 14

# When ISIS is complaining that you are downloading too fast (Connection Aborted) ↓ s are waited.
sleep_time_for_isis = 3

# Will retry downloading a url ↓ times. If it fails, that MediaContainer will not get downloaded.
num_tries_download = 5

# Will fail a download if ISIS is not responding in ↓ amount of s
download_timeout = 10


# When cancelling downloads it is waited ↓ s to check if the downloads have finished.
sleep_time_for_download_interrupt = 0.25

# A constant to detect if you are on windows.
is_windows = platform.system() == "Windows"

# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.01

if "pytest" in sys.modules:
    # Yes, this is evil. But I don't want to ruin the directory of the user.
    _working_dir_location = working_dir_location
    working_dir_location = os.path.join(os.path.expanduser("~"), "test_isis_dl")

# </ Miscellaneous options >
