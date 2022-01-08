import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, List

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import CourseDownloader, RequestHelper, PreMediaContainer
from isisdl.backend.utils import args, path, calculate_local_checksum
from isisdl.bin.sync_database import restore_database_state, delete_missing_files_from_database
from isisdl.settings import course_dir_location
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


def test_remove_database_and_rediscover(database_helper: DatabaseHelper, request_helper: RequestHelper) -> None:
    assert request_helper.session is not None
    prev_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}

    possible_duplicates: List[PreMediaContainer] = []
    for course in request_helper.courses:
        available_videos = course.download_videos(request_helper.session)
        available_documents = course.download_documents(request_helper)

        videos, documents = defaultdict(list), defaultdict(list)
        for item in available_videos:
            videos[item.size].append(item)

        for item in available_documents:
            documents[item.size].append(item)

        for row in {**videos, **documents}.values():
            if len(row) > 1:
                possible_duplicates.extend(row)

    for item in possible_duplicates:
        try:
            prev_ids.remove(item.file_id)
        except KeyError:
            pass

    database_helper.delete_file_table()
    restore_database_state(request_helper, True)

    # Now check if everything is restored (except `possible_duplicates`)
    recovered_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}

    # state ⊇ prev_ids
    assert len(prev_ids - recovered_ids) <= 20


def sample_files(num: int) -> List[Path]:
    files = [item for item in Path(path(course_dir_location)).rglob("*") if item.is_file()]
    random.shuffle(files)

    return files[:num]


def get_checksums_of_files(files: List[Path]) -> List[str]:
    return [calculate_local_checksum(item) for item in files]


def test_move_files(database_helper: DatabaseHelper, request_helper: RequestHelper) -> None:
    to_move = sample_files(10)
    new_files = []
    checksums = get_checksums_of_files(to_move)

    for i, item in enumerate(to_move):
        name, ext = os.path.splitext(item.name)
        new_name = name + " uwu " + ext
        new_files.append(new_name)
        item.rename(os.path.join(item.parent, new_name))

    database_helper.delete_file_table()
    restore_database_state(request_helper, False)

    for csum, new_name in zip(checksums, new_files):
        assert database_helper.get_name_by_checksum(csum) == new_name


def test_delete_files(database_helper: DatabaseHelper) -> None:
    to_delete = sample_files(10)
    checksums = get_checksums_of_files(to_delete)

    for item in to_delete:
        item.unlink()

    delete_missing_files_from_database()

    assert len([database_helper.get_name_by_checksum(item) for item in checksums]) < 8

    # for csum in checksums:
    #     assert database_helper.get_name_by_checksum(csum) is None
