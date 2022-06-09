import os
import sys
from hashlib import sha256

from cryptography.hazmat.primitives.hashes import SHA3_512

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.settings import working_dir_location, _working_dir_location, database_file_location, checksum_algorithm, checksum_num_bytes, password_hash_iterations, \
    password_hash_algorithm, password_hash_length, download_progress_bar_resolution, status_chop_off, status_time, env_var_name_username, env_var_name_password, \
    enable_multithread, download_chunk_size, download_static_sleep_time, num_tries_download, download_timeout, download_timeout_multiplier, _status_time, config_dir_location, \
    example_config_file_location, config_file_location, systemd_timer_file_location, systemd_service_file_location, lock_file_location, enable_lock, error_directory_location, master_password, \
    status_progress_bar_resolution, token_queue_refresh_rate, token_queue_download_refresh_rate, discover_num_threads, systemd_dir_location, error_text, \
    throttler_low_prio_sleep_time, subscribed_courses_file_location, subscribe_num_threads, _config_dir_location, _config_file_location, _example_config_file_location, export_config_file_location, \
    _export_config_file_location, is_static, python_executable, is_autorun
from isisdl.utils import Config


def test_settings() -> None:
    assert working_dir_location == os.path.join(os.path.expanduser("~"), "testisisdl")
    assert database_file_location == os.path.join(".state.db")

    assert lock_file_location == ".lock"
    assert enable_lock is True

    assert subscribed_courses_file_location == "subscribed_courses.json"
    assert 16 <= subscribe_num_threads <= 48

    assert error_directory_location == ".errors"
    assert error_text == "\033[1;91mError:\033[0m"

    assert is_static is False
    assert python_executable == sys.executable
    assert is_autorun is False

    assert checksum_algorithm == sha256
    assert 1024 <= checksum_num_bytes <= 1024 * 1024

    assert password_hash_algorithm == SHA3_512
    assert 390_000 <= password_hash_iterations <= 1_000_000
    assert password_hash_length == 32
    assert master_password == "eeb36e726e3ffec16da7798415bb4e531bf8a57fbe276fcc3fc6ea986cb02e9a"

    assert 30 <= status_progress_bar_resolution <= 60
    assert 8 <= download_progress_bar_resolution <= 12
    assert 2 <= status_chop_off <= 3

    assert 2 ** 15 <= download_chunk_size <= 2 ** 17
    assert 16 <= discover_num_threads <= 48
    assert 3 <= num_tries_download <= 5
    assert 1 <= download_timeout <= 10
    assert 1.5 <= download_timeout_multiplier <= 3.5
    assert 0 <= download_static_sleep_time <= 4

    assert 0.001 <= token_queue_refresh_rate <= 0.2
    assert 1 <= token_queue_download_refresh_rate <= 5
    assert 0.01 <= throttler_low_prio_sleep_time <= 1

    assert subscribed_courses_file_location == "subscribed_courses.json"
    assert 16 <= subscribe_num_threads <= 64

    assert config_dir_location == os.path.join(os.path.expanduser("~"), ".config", "testisisdl")
    assert config_file_location == os.path.join(config_dir_location, "config.yaml")
    assert example_config_file_location == os.path.join(config_dir_location, "example.yaml")
    assert export_config_file_location == os.path.join(config_dir_location, "export.yaml")

    assert systemd_dir_location == os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
    assert systemd_timer_file_location == os.path.join(systemd_dir_location, "isisdl.timer")
    assert systemd_service_file_location == os.path.join(systemd_dir_location, "isisdl.service")

    assert env_var_name_username == "ISISDL_USERNAME"
    assert env_var_name_password == "ISISDL_PASSWORD"

    assert enable_multithread is True

    assert _working_dir_location == os.path.join(os.path.expanduser("~"), "isisdl")
    assert _config_dir_location == os.path.join(os.path.expanduser("~"), ".config", "isisdl")
    assert _config_file_location == os.path.join(_config_dir_location, "config.yaml")
    assert _example_config_file_location == os.path.join(_config_dir_location, "example.yaml")
    assert _export_config_file_location == os.path.join(_config_dir_location, "export.yaml")
    assert 0.1 <= _status_time <= 1
    assert status_time == 1000000


def test_database_version(database_helper: DatabaseHelper) -> None:
    assert database_helper.get_database_version() == Config.default("database_version")
