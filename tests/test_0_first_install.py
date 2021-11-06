import os

from isis_dl.share.settings import working_dir_location, intern_dir_location, download_dir_location, settings_file_location, log_dir_location, whitelist_file_name_location, \
    blacklist_file_name_location, course_name_to_id_file_location, password_dir, clear_password_file, encrypted_password_file, is_windows
from isis_dl.share.utils import path


def test_working_dir_structrue():
    assert os.path.exists(path(working_dir_location))
    assert os.path.exists(path(download_dir_location))
    assert os.path.exists(path(intern_dir_location))

    assert os.path.exists(path(log_dir_location))
    assert os.path.exists(path(whitelist_file_name_location))
    assert os.path.exists(path(blacklist_file_name_location))
    assert os.path.exists(path(course_name_to_id_file_location))

    assert os.path.exists(path(password_dir))
    assert os.path.exists(path(clear_password_file))
    assert not os.path.exists(path(encrypted_password_file))
    # assert not os.path.exists(path(already_prompted_file))


def test_settings_link():
    import isis_dl
    assert is_windows or isis_dl.share.settings.__file__ == os.readlink(path(settings_file_location))
