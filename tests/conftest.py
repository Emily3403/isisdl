import os
import shutil
from typing import Any

from pytest import fixture

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import RequestHelper
from isisdl.backend.utils import startup, path, User


def pytest_configure() -> None:
    assert path() == os.path.join(os.path.expanduser("~"), "test_isisdl")
    startup()


def pytest_unconfigure() -> None:
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


@fixture(scope="session")
def request_helper() -> Any:
    helper = RequestHelper(user())
    yield helper
