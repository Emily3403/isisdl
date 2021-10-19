import os
from hashlib import sha256

from cryptography.hazmat.primitives import hashes

# In this file you will find various constants that dictate how isis_dl works.
# First up there are things that you may want to change.
# In the second part only change stuff if you know what you are doing.

# < Directory options >

working_dir = os.path.join(os.path.expanduser("~"), "isis_dl_downloads")  # The directory where everything lives in
download_dir = "Courses/"  # The directory where files get saved to
temp_dir = ".temp/"  # The directory used to save temporary files e.g. .zip files

intern_dir = ".intern/"  # The directory for intern stuff such as passwords

# </ Directory options >

# < Checksums >

# Checksums are dumped into this file on a per-course basis.
checksum_file = ".checksums.json"
checksum_algorithm = sha256

# Format:
# <extension>: (<#bytes to ignore>, <#bytes to read>)
checksum_num_bytes = {
    ".pdf": (0, None),
    ".mp4": (0, 512),
    ".zip": (512, 512),
    None: (0, 512),
}

# </ Checksums >


# < Password / Cryptography options >

# Note: The *_password_file are prepended with password_dir.  # TODO: Get rid of this functionality and move it to here
password_dir = os.path.join(intern_dir, "Passwords/")
clear_password_file = "Pass.clean"
encrypted_password_file = "Pass.encrypted"

# Beware: Changing any of these options means loosing compatibility with the old password file.
hash_iterations = 10 ** 1
hash_algorithm = hashes.SHA3_512()
hash_length = 32

# < Password / Cryptography options >

#

# Begin second part.


# < Miscellaneous options >

enable_multithread = True

# </ Miscellaneous options >
