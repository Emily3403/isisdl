import os
from hashlib import sha256

from cryptography.hazmat.primitives.hashes import SHA3_512

from isisdl.share.settings import working_dir_location, _working_dir_location, course_dir_location, intern_dir_location, settings_file_location, database_file_location, set_database_to_memory, \
    checksum_algorithm, checksum_num_bytes, checksum_base_skip, sync_database_num_threads, hash_iterations, hash_algorithm, hash_length, \
    progress_bar_resolution, status_chop_off, status_time, env_var_name_username, env_var_name_password, env_var_name_encrypted_password, enable_multithread, download_chunk_size, \
    sleep_time_for_isis, num_tries_download, download_timeout, download_timeout_multiplier


def test_settings() -> None:
    fix_items = {
        working_dir_location: os.path.join(os.path.expanduser("~"), "test_isisdl"),
        _working_dir_location: os.path.join(os.path.expanduser("~"), "isisdl_downloads"),
        course_dir_location: "Courses",
        intern_dir_location: ".intern",
        settings_file_location: os.path.join(intern_dir_location, "settings.py"),
        database_file_location: os.path.join(intern_dir_location, "state.db"),
        set_database_to_memory: False,
        checksum_algorithm: sha256,
        hash_algorithm: SHA3_512,
        env_var_name_username: "ISISDL_USERNAME",
        env_var_name_password: "ISISDL_PASSWORD",
        env_var_name_encrypted_password: "ISISDL_ENC_PASSWORD",
        # enable_multithread: True,

    }

    variable_items = {
        checksum_num_bytes: (1024 * 3, 1024 * 5),
        checksum_base_skip: (1.5, 2.5),
        sync_database_num_threads: (16, 48),
        hash_iterations: (390_000, 1_000_000),
        hash_length: (32, 32),
        progress_bar_resolution: (8, 12),
        status_chop_off: (3, 3),
        status_time: (0.1, 0.5),
        download_chunk_size: (2 ** 13, 2 ** 16),
        sleep_time_for_isis: (0, 4),
        num_tries_download: (3, 5),
        download_timeout: (3, 6),
        download_timeout_multiplier: (1.5, 2.5),
    }

    for a, b in fix_items.items():
        assert a == b

    for a, (b, c) in variable_items.items():
        assert b <= a <= c
