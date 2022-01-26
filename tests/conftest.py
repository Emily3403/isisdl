import os
import shutil
from typing import Any

from pytest import fixture

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import RequestHelper
from isisdl.backend.utils import startup, path, User
from isisdl.settings import is_windows, database_file_location


def pytest_configure() -> None:
    assert path() == os.path.join(os.path.expanduser("~"), "test_isisdl")
    startup()


def pytest_unconfigure() -> None:
    # config_helper.close_connection()  TODO
    if is_windows or True:
        for file in os.listdir(path()):
            if file != database_file_location:
                shutil.rmtree(path(file))
    else:
        shutil.rmtree(path())


def user() -> User:
    username, password = os.getenv("ISISDL_ACTUAL_USERNAME"), os.getenv("ISISDL_ACTUAL_PASSWORD")
    assert username is not None
    assert password is not None

    return User(username, password)


@fixture(scope="session")
def database_helper() -> Any:
    helper = DatabaseHelper()
    yield helper

    helper.close_connection()


@fixture(scope="session")
def request_helper() -> Any:
    helper = RequestHelper(user())
    yield helper
