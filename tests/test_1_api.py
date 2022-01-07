from typing import Any

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.utils import args
from isisdl.backend.request_helper import CourseDownloader, RequestHelper
from tests.conftest import user


def test_database_helper(database_helper: DatabaseHelper) -> None:
    # assert database_helper.get_state() == [[], [], []]
    pass


def test_request_helper(request_helper: RequestHelper) -> None:
    assert request_helper is not None


def test_course_downloader(request_helper: RequestHelper, monkeypatch: Any) -> None:
    args.num_threads = 16

    course_downloader = CourseDownloader(user())
    course_downloader.start()

# TODO: Check file name scheme
