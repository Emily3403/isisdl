import os

import pytest

from isisdl.settings import working_dir_location, intern_dir_location, course_dir_location, settings_file_location, is_windows, database_file_location
from isisdl.backend.utils import path, startup

import isisdl.__main__

settings_file = os.path.abspath(isisdl.settings.__file__)
main_file = os.path.abspath(isisdl.__main__.__file__)


def test_working_dir_structure() -> None:
    locations = [
        working_dir_location,
        course_dir_location,
        intern_dir_location,
        database_file_location,
    ]

    for item in locations:
        assert os.path.exists(path(item))


def assert_settings_works() -> None:
    if is_windows:
        return

    assert settings_file == os.readlink(path(settings_file_location))


def test_settings_link_remove() -> None:
    if is_windows:
        return

    os.unlink(path(settings_file_location))

    with pytest.raises(FileNotFoundError):
        assert_settings_works()

    startup()

    assert_settings_works()


def test_settings_link_wrong_symlink() -> None:
    if is_windows:
        return

    os.unlink(path(settings_file_location))
    os.symlink(main_file, path(settings_file_location))

    startup()

    assert_settings_works()


def test_settings_link_broken_symlink() -> None:
    if is_windows:
        return

    os.unlink(path(settings_file_location))
    os.symlink("uwu", path(settings_file_location))

    startup()

    assert_settings_works()
