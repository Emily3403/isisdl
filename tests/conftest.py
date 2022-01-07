import os
import shutil

from pytest import fixture

from database_helper import DatabaseHelper
from isisdl.share.utils import startup, path, User
from request_helper import RequestHelper


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
def database_helper() -> DatabaseHelper:
    helper = DatabaseHelper()
    yield helper


@fixture(scope="session")
def request_helper() -> RequestHelper:
    helper = RequestHelper(user())
    yield helper
