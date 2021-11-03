import datetime
import os
from hashlib import sha256

from isis_dl.share.settings import checksum_num_bytes, progress_bar_resolution, download_chunk_size, enable_multithread, sleep_time_for_isis, \
    sleep_time_for_download_interrupt, log_clear_screen, num_sessions, working_dir_location, download_dir_location, intern_dir_location, unpacked_archive_dir_location, unpacked_archive_suffix, \
    settings_file_location, log_dir_location, log_file_location, whitelist_file_name_location, blacklist_file_name_location, course_name_to_id_file_location, checksum_file, checksum_algorithm, \
    ExtensionNumBytes, checksum_range_parameter_ignored, password_dir, clear_password_file, encrypted_password_file, already_prompted_file, hash_iterations, hash_length, \
    env_var_name_username, env_var_name_password, env_var_name_encrypted_password, debug_mode, print_status, status_time, token_queue_refresh_rate


def test_working_dir_location():
    assert working_dir_location == os.path.join(os.path.expanduser("~"), "isis_dl_downloads")


def test_download_dir_location():
    assert download_dir_location == "Courses/"


def test_intern_dir_location():
    assert intern_dir_location == ".intern/"


def test_unpacked_archive_dir_location():
    assert unpacked_archive_dir_location == "UnpackedArchives/"


def test_unpacked_archive_suffix():
    assert unpacked_archive_suffix == ".unpacked"


def test_settings_file_location():
    assert settings_file_location == os.path.join(intern_dir_location, "settings.py")


def test_log_dir_location():
    assert log_dir_location == os.path.join(intern_dir_location, "logs/")


def test_log_file_location():
    assert log_file_location.startswith("log") and ".log" in log_file_location


def test_whitelist_file_name_location():
    assert whitelist_file_name_location == os.path.join(intern_dir_location, "whitelist.txt")


def test_blacklist_file_name_location():
    assert blacklist_file_name_location == os.path.join(intern_dir_location, "blacklist.txt")


def test_course_name_to_id_file_location():
    assert course_name_to_id_file_location == os.path.join(intern_dir_location, "id_file.json")


def test_checksum_file():
    assert checksum_file == ".checksums.json"


def test_checksum_algorithm():
    assert checksum_algorithm == sha256


def test_checksum_num_bytes():
    assert checksum_num_bytes == {
        ".zip": ExtensionNumBytes(skip_header=512),

        None: ExtensionNumBytes(),
    }


def test_checksum_range_parameter_ignored():
    assert 512 <= checksum_range_parameter_ignored <= 1024


def test_password_dir():
    assert password_dir == os.path.join(intern_dir_location, "Passwords/")


def test_clear_password_file():
    assert clear_password_file == os.path.join(password_dir, ".pass.clean")


def test_encrypted_password_file():
    assert encrypted_password_file == os.path.join(password_dir, ".pass.encrypted")


def test_already_prompted_file():
    assert already_prompted_file == os.path.join(password_dir, ".pass.prompted")


def test_hash_iterations():
    assert 320_000 <= hash_iterations <= 1_000_000


def test_hash_length():
    assert 32 <= hash_length <= 64


def test_progress_bar_resolution():
    assert 4 <= progress_bar_resolution <= 32


def test_num_sessions():
    assert 1 <= num_sessions <= 8


def test_env_var_name_username():
    assert env_var_name_username == "ISIS_DL_USERNAME"


def test_env_var_name_password():
    assert env_var_name_password == "ISIS_DL_PASSWORD"


def test_env_var_name_encrypted_password():
    assert env_var_name_encrypted_password == "ISIS_DL_ENC_PASSWORD"


def test_debug_mode():
    assert debug_mode is False


def test_enable_multithread():
    assert enable_multithread is True


def test_print_status():
    assert print_status is True


def test_log_clear_screen():
    assert log_clear_screen is True


def test_status_time():
    assert 0.05 <= status_time <= 1


def test_download_chunk_size():
    assert 2 ** 11 <= download_chunk_size <= 2 ** 16


def test_sleep_time_for_isis():
    assert 1 <= sleep_time_for_isis <= 3


def test_sleep_time_for_download_interrupt():
    assert 0.05 <= sleep_time_for_download_interrupt < 1


def test_token_queue_refresh_rate():
    assert 0.001 <= token_queue_refresh_rate <= 1
