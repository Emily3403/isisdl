import datetime
import os
from cryptography.hazmat.primitives import hashes

# In this file you will find various constants that dictate how isis_dl works.
# First up there are things that you may want to change.
# In the second part only change stuff if you know what you are doing.

# < Directory options >

working_dir = os.path.join(os.path.expanduser("~"), "isis_dl_downloads")
download_dir = "Courses/"
temp_dir = ".temp/"

# This directory is used to do "intelligent" stuff
intern_dir = ".intern/"

# </ Directory options >

# < Checksums >

# Checksums are dumped into this file on a per-course basis.
checksum_file = ".checksums.json"

metadata_file = ".metadata.json"

# Format:
# <extension>: (<#bytes to ignore>, <#bytes to read>)
checksum_num_bytes = {
    ".pdf": (0, None),
    ".mp4": (0, 512),
    ".zip": (1024, None),
    None: (0, 512),
}

# </ Checksums >


# < Password / Cryptography options >

# Note: The *_password_file are prepended with password_dir.
password_dir = os.path.join(intern_dir, "Passwords/")
clear_password_file = "Pass.clean"
encrypted_password_file = "Pass.encrypted"

# Beware: Changing any of these options means loosing compatibility with the old password file.
hash_iterations = 10 ** 1
hash_algorithm = hashes.SHA3_512()
hash_length = 32

# < Password / Cryptography options >

#

# < Miscellaneous options >


# </ Miscellaneous options >

#

# Begin second part.
# !! Only change stuff if you know what you are doing !!


# < Miscellaneous options >

enable_multithread = False

# </ Miscellaneous options >
