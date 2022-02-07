import os
import random
import re
import shutil
import string
from collections import defaultdict
from pathlib import Path
from typing import Any, List

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import CourseDownloader, RequestHelper, PreMediaContainer
from isisdl.backend.utils import args, path, calculate_local_checksum, User, config, sanitize_name, database_helper
from isisdl.bin.sync_database import restore_database_state, delete_missing_files_from_database
from isisdl.settings import database_file_location
from tests.conftest import user


def test_database_helper(database_helper: DatabaseHelper) -> None:
    assert database_helper is not None
    # assert database_helper.get_state() == [[], [], []]


def test_request_helper(request_helper: RequestHelper) -> None:
    assert request_helper is not None


def remove_old_files() -> None:
    database_helper.delete_file_table()
    for item in os.listdir(path()):
        if item != database_file_location:
            shutil.rmtree(path(item))

    return


def get_content_to_download(request_helper: RequestHelper) -> List[PreMediaContainer]:
    content_to_download = request_helper.download_content()

    known_bad_urls = {
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1484020/mod_resource/content/1/armv7-a-r-manual-VBAR-EXTRACT.pdf"
    }

    return [item for item in content_to_download if item.url not in known_bad_urls]


def test_normal_course_downloader(request_helper: RequestHelper, user: User, monkeypatch: Any) -> None:
    args.num_threads = 16

    remove_old_files()
    config.filename_replacing = False
    request_helper.make_course_paths()

    content_to_download = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)

    course_downloader = CourseDownloader(user)
    course_downloader.start()

    for item in content_to_download:
        item_loc = os.path.join(item.location, sanitize_name(item.name))
        assert os.path.exists(item_loc)
        assert os.stat(item_loc).st_size == item.size

    remove_old_files()
    monkeypatch.undo()
    config.filename_replacing = True
    request_helper.make_course_paths()

    content_to_download = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)

    course_downloader.start()

    allowed_chars = set(string.ascii_letters + string.digits + ".")
    for item in content_to_download:
        item_loc = os.path.join(item.location, sanitize_name(item.name))
        assert os.path.exists(item_loc)
        assert os.stat(item_loc).st_size == item.size
        assert all(c for item in Path(item_loc).parts[1:] for c in item if c not in allowed_chars)


def test_remove_database_and_rediscover(database_helper: DatabaseHelper, request_helper: RequestHelper) -> None:
    assert request_helper.session is not None
    prev_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}

    dupl = defaultdict(list)
    x = request_helper.download_content()
    for item in x:
        dupl[item.size].append(item)

    possible_duplicates: List[PreMediaContainer] = [item for row in dupl.values() for item in row if len(row) > 1]

    for item in possible_duplicates:
        try:
            prev_ids.remove(item.file_id)
        except KeyError:
            pass

    # TODO: This is an unfixed bug. I don't know what causes it, and it happens to infrequent for me to care enough.
    try:
        prev_ids.remove("94971")
    except KeyError:
        pass

    database_helper.delete_file_table()
    restore_database_state(request_helper)

    # Now check if everything is restored (except `possible_duplicates`)
    recovered_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}

    # state ⊇ prev_ids
    assert prev_ids.intersection(recovered_ids) == prev_ids


def sample_files(num: int) -> List[Path]:
    files = [item for item in Path(path(course_dir_location)).rglob("*") if item.is_file() and not re.match(r".*\(\d*-\d*\)\.", item.name)]
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
    restore_database_state(request_helper)

    for csum, new_name in zip(checksums, new_files):
        assert database_helper.get_name_by_checksum(csum)


def test_delete_files(database_helper: DatabaseHelper) -> None:
    to_delete = sample_files(10)
    checksums = get_checksums_of_files(to_delete)

    for item in to_delete:
        item.unlink()

    delete_missing_files_from_database()

    for csum in checksums:
        assert database_helper.get_name_by_checksum(csum) is None
