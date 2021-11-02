import os

from isis_dl.share.settings import checksum_num_bytes, progress_bar_resolution, download_chunk_size, enable_multithread, sleep_time_for_isis, \
    sleep_time_for_download_interrupt, log_clear_screen, num_sessions, working_dir_location, default_download_max_speed


def test_working_dir_location():
    assert working_dir_location == os.path.join(os.path.expanduser("~"), "isis_dl_downloads")


def test_checksum_num_bytes():
    for k, v in checksum_num_bytes.items():
        assert v[1] is None or v[1] >= 64


def test_progress_bar_resolution():
    assert 8 <= progress_bar_resolution <= 128


def test_enable_multithread():
    assert enable_multithread is True


def test_download_chunk_size():
    assert 2 ** 13 <= download_chunk_size <= 2 ** 17


def test_sleep_time_for_isis():
    assert 0.5 <= sleep_time_for_isis <= 10


def test_sleep_time_for_download_interrupt():
    assert 0 < sleep_time_for_download_interrupt <= 1


def test_log_clear_screen():
    assert log_clear_screen is True


def test_num_sessions():
    assert 1 <= num_sessions <= 16


def test_default_download_max_speed():
    assert 20 <= default_download_max_speed <= 100
