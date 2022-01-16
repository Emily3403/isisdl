import os
import platform
import sys
from hashlib import sha256
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.hashes import SHA3_512

if TYPE_CHECKING:
    pass

# In this file you will find various constants that dictate how isisdl works.
# First up there are things that you may want to change.
# In the second part you should only change stuff if you know what you are doing.

# < Directory options >

# The directory where everything lives in.
# Note: If you want to expand your "~" use `os.path.expanduser("~")`. Otherwise a Directory with the literal `~` will be created in the current working directory.
working_dir_location = os.path.join(os.path.expanduser("~"), "isisdl_downloads")

# The directory where the courses are listed.
# In the courses house all the files which are downloadable.
course_dir_location = "Courses"

# The directory of the database and other persistent functionality.
intern_dir_location = ".intern"

# Will create a symlink to the settings file in the intern dir.
settings_file_location = os.path.join(intern_dir_location, "settings.py")

# Will create the corresponding SQlite Database
database_file_location = os.path.join(intern_dir_location, "state.db")

# Creates a mock database to play on. Done with :memory:
set_database_to_memory = False

# </ Directory options >

# < Checksums >

# A checksum is calculated with this algorithm
checksum_algorithm = sha256

# The number of bytes sampled
checksum_num_bytes = 1024 * 4

# Skips $`checksum_base_skip` ^ i$ bytes per calculation → O(log(n)) time :O
checksum_base_skip = 2

# Number of threads to use for the database requests
sync_database_num_threads = 32

# </ Checksums >


# < Password / Cryptography options >

# Beware: Changing any of these options means loosing compatibility with the old password file.

# This is what Django recommends as of January 2021 (https://github.com/django/django/blob/main/django/contrib/auth/hashers.py#L274)
hash_algorithm = SHA3_512
hash_iterations = 390_000
hash_length = 32

# < Password / Cryptography options >

# < Status options >

# The number of places the progress bar has.
progress_bar_resolution = 10

# Chop off the last ↓ characters of the status message for a ...
status_chop_off = 2

# The refresh time for the status message
status_time = 0.25

# </ Status options >


# < Miscellaneous options >

# If you want to use username and password set these variables accordingly.
env_var_name_username = "ISISDL_USERNAME"
env_var_name_password = "ISISDL_PASSWORD"

# Output os.
config_clear_screen = True

# </ Miscellaneous options >

# Begin second part.
# Don't change anything below this otherwise it might have negative implications. Or do… I don't care :D

# < Download options >
enable_multithread = True

# Sets the chunk size for a download.
download_chunk_size = 2 ** 16

# When ISIS is complaining that you are downloading too fast (Connection Aborted) ↓ s are waited.
sleep_time_for_isis = 3

# Will retry downloading an url ↓ times. If it fails, that MediaContainer will not get downloaded.
num_tries_download = 5

# Will fail a download if ISIS is not responding in ↓ amount of s
download_timeout = 6

# Adds `download_timeout_multiplier ** (0.5 * i)` of timeout every iteration
download_timeout_multiplier = 2

# </ Download options >

# < Miscellaneous options >

# A constant to detect if you are on Windows.
is_windows = platform.system() == "Windows"

# Check if the user is executing the library for the first time → state.db should be missing
is_first_time = not os.path.exists(os.path.join(working_dir_location, database_file_location))

# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.1

# Collect the amount of handed out tokens in the last ↓ secs
token_queue_download_refresh_rate = 3

# Yes, changing behaviour when tested is evil. But I'm doing so in order to protect my `~/isisdl_downloads` directory.
is_testing = "pytest" in sys.modules
if is_testing:
    _working_dir_location = working_dir_location
    working_dir_location = os.path.join(os.path.expanduser("~"), "test_isisdl")
    status_time = 2
    download_timeout = 3

# This number represent seconds of video.    (ISIS does not offer a better "size" api…)
testing_download_video_size = 3600 * 1

# Number of bytes downloaded for documents.
testing_download_documents_size = 1_000_000_000

# </ Miscellaneous options >
