import os
import shutil

import pytest

from isisdl.backend.api import CourseDownloader
from isisdl.share.settings import working_dir_location, already_prompted_file, _working_dir_location, clear_password_file
from isisdl.share.utils import startup, path, User


def pytest_configure():
    assert working_dir_location == os.path.join(os.path.expanduser("~"), "test_isisdl")
    startup()

    # Disable the "do you want to save your password" prompt (for now)
    with open(path(already_prompted_file), "w"):
        pass


def pytest_unconfigure():
    shutil.rmtree(path())


@pytest.fixture
def username():
    return os.getenv("ISISDL_ACTUAL_USERNAME")


@pytest.fixture
def password():
    return os.getenv("ISISDL_ACTUAL_USERNAME")


def make_dl():
    if (usr := os.getenv("ISISDL_ACTUAL_USERNAME")) is not None and (pw := os.getenv("ISISDL_ACTUAL_PASSWORD")) is not None:
        user = User(usr, pw)

    else:
        with open(os.path.join(_working_dir_location, clear_password_file)) as f:
            user = User(*f.read().splitlines())

    return CourseDownloader(user)


@pytest.fixture
def course_downloader():
    return make_dl()
