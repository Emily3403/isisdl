import datetime
import os
import platform
from hashlib import sha256

from cryptography.hazmat.primitives import hashes

# In this file you will find various constants that dictate how isis_dl works.
# First up there are things that you may want to change.
# In the second part only change stuff if you know what you are doing.

# < Directory options >

# The directory where everything lives in.
# Note that if you want to expand your "~" use `os.path.expanduser("~")`. Otherwise a Directory with the literal `~` will be created in the current working directory
working_dir_location = os.path.join(os.path.expanduser("~"), "isis_dl")

# The directory where files get saved to
download_dir_location = "Courses/"

# Temporary directory. Currently not used.
temp_dir_location = ".temp/"

# The directory for intern stuff such as passwords
intern_dir_location = ".intern/"

# The directory for intern stuff such as passwords
unpacked_archive_dir_location = "UnpackedArchives/"
unpacked_archive_suffix = ".unzipped"

# Will create a symlink in the working_dir.
settings_file_location = os.path.join(intern_dir_location, "settings.py")

# Logs
log_dir_location = os.path.join(intern_dir_location, "logs/")
log_file_location = os.path.join(log_dir_location, "log" + datetime.datetime.now().strftime("-%Y-%m-%d-%H:%M:%S") + ".log")

whitelist_file_name_location = os.path.join(intern_dir_location, "whitelist.txt")
blacklist_file_name_location = os.path.join(intern_dir_location, "blacklist.txt")
course_name_to_id_file_location = os.path.join(intern_dir_location, "id_file.json")

# </ Directory options >

# < Checksums >

# Checksums are dumped into this file on a per-course basis.
checksum_file = ".checksums.json"
checksum_algorithm = sha256

# Format:
# <extension>: (<#bytes to ignore>, <#bytes to read>)
checksum_num_bytes = {
    ".pdf": (0, None),
    ".tex": (0, None),

    ".zip": (512, 512),

    None: (0, 512),
}

# </ Checksums >


# < Password / Cryptography options >

password_dir = os.path.join(intern_dir_location, "Passwords/")
clear_password_file = os.path.join(password_dir, "Pass.clean")
encrypted_password_file = os.path.join(password_dir, "Pass.encrypted")

already_prompted_file = os.path.join(password_dir, "Pass.prompted")

# Beware: Changing any of these options means loosing compatibility with the old password file.
hash_iterations = 10 ** 1
hash_algorithm = hashes.SHA3_512()
hash_length = 32

# < Password / Cryptography options >

#

# Begin second part.


# < Miscellaneous options >

try:
    with open("VERSION") as f:
        version = f.read().strip()

except FileNotFoundError:
    version = "0.0.0"

# The number of places the progress bar has. Feel free to change!
progress_bar_resolution = 16

# When this percentage is reached the progress is not buffered with \n's
ratio_to_skip_big_progress = 0.7

enable_multithread = True

# At least 2 ** 10 otherwise the f.write() operation is the bottleneck.
# Tested with 1 Thread. Can achieve 30-40 MiB/s download
# Times:
#   2 ** 10 → 74s
#   2 ** 11 → 59s
#   2 ** 12 → 51s
#   2 ** 13 → 50s
#   2 ** 14 → 51s
download_chunk_size = 2 ** 12

sleep_time_for_isis = 3  # in s
sleep_time_for_download_interrupt = 0.25  # in s

is_windows = platform.system() == "Windows"

log_clear_screen = True


num_sessions = 4

# </ Miscellaneous options >
