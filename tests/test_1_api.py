from typing import Any

from database_helper import DatabaseHelper
from isisdl.share.utils import args
from request_helper import check_for_conflicts_in_files, CourseDownloader, RequestHelper
from tests.conftest import user


def test_database_helper(database_helper: DatabaseHelper) -> None:
    # assert database_helper.get_state() == [[], [], []]
    pass


def test_request_helper(request_helper: RequestHelper) -> None:
    assert request_helper is not None


def test_course_downloader(request_helper: RequestHelper, monkeypatch: Any) -> None:
    pre_containers = request_helper.download_content()
    check_for_conflicts_in_files(pre_containers)
    args.num_threads = 16

    course_downloader = CourseDownloader(user())
    course_downloader.start()
