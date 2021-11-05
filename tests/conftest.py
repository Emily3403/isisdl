import os

import pytest

from isis_dl.share.settings import working_dir_location
from isis_dl.share.utils import startup


def pytest_configure():
    assert working_dir_location == os.path.join(os.path.expanduser("~"), "test_isis_dl")
    startup()

# def pytest_unconfigure():
#     shutil.rmtree(path())


@pytest.fixture
def user():
    return os.getenv("ISIS_DL_ACTUAL_USERNAME")


@pytest.fixture
def password():
    return os.getenv("ISIS_DL_ACTUAL_USERNAME")
