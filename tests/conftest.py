import os
from pathlib import Path
from typing import Any

from pytest import fixture

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import RequestHelper
from isisdl.utils import startup, path, User


def pytest_configure() -> None:
    assert path() == Path(os.path.expanduser("~"), "testisisdl")
    startup()


@fixture(scope="session")
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
def request_helper(user: User) -> Any:
    helper = RequestHelper(user)
    yield helper
