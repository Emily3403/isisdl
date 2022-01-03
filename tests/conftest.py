import os
import shutil
from typing import cast

import pytest

from isisdl.share.settings import working_dir_location, _working_dir_location, clear_password_file
from isisdl.share.utils import startup, path, User
from request_helper import CourseDownloader


def pytest_configure() -> None:
    assert working_dir_location == os.path.join(os.path.expanduser("~"), "test_isisdl")
    startup()


def pytest_unconfigure() -> None:
    shutil.rmtree(path())


@pytest.fixture
def username() -> str:
    return cast(str, os.getenv("ISISDL_ACTUAL_USERNAME"))


@pytest.fixture
def password() -> str:
    return cast(str, os.getenv("ISISDL_ACTUAL_USERNAME"))


def make_dl() -> CourseDownloader:
    if (usr := os.getenv("ISISDL_ACTUAL_USERNAME")) is not None and (pw := os.getenv("ISISDL_ACTUAL_PASSWORD")) is not None:
        user = User(usr, pw)

    else:
        with open(os.path.join(_working_dir_location, clear_password_file)) as f:
            user = User(*f.read().splitlines())

    return CourseDownloader(user)


@pytest.fixture
def course_downloader() -> CourseDownloader:
    return make_dl()
