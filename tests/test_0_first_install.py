import os

import pytest

from isisdl.settings import working_dir_location, is_windows, database_file_location
from isisdl.backend.utils import path, startup

import isisdl.__main__

settings_file = os.path.abspath(isisdl.settings.__file__)
main_file = os.path.abspath(isisdl.__main__.__file__)


def test_working_dir_structure() -> None:
    locations = [
        working_dir_location,
        database_file_location,
    ]

    for item in locations:
        assert os.path.exists(path(item))
