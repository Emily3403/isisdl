import os
import random
import shutil
import string
from collections import defaultdict
from pathlib import Path
from typing import Any, List

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import CourseDownloader, RequestHelper, PreMediaContainer
from isisdl.backend.utils import args, path, calculate_local_checksum, User, config, _course_downloader_transformation
from isisdl.bin.sync_database import restore_database_state, delete_missing_files_from_database
from isisdl.settings import database_file_location, lock_file_location


def test_database_helper(database_helper: DatabaseHelper) -> None:
    assert database_helper is not None
    # assert database_helper.get_state() == [[], [], []]


def test_request_helper(request_helper: RequestHelper) -> None:
    assert request_helper is not None


def remove_old_files(database_helper: DatabaseHelper) -> None:
    database_helper.delete_file_table()
    for item in os.listdir(path()):
        if item != database_file_location and item != lock_file_location:
            shutil.rmtree(path(item))

    return


def get_content_to_download(request_helper: RequestHelper) -> List[PreMediaContainer]:
    content_to_download = _course_downloader_transformation(request_helper.download_content())

    known_bad_urls = {
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1484020/mod_resource/content/1/armv7-a-r-manual-VBAR-EXTRACT.pdf"
    }

    return [item for item in content_to_download if item.url not in known_bad_urls]


def test_normal_course_downloader(request_helper: RequestHelper, database_helper: DatabaseHelper, user: User, monkeypatch: Any) -> None:
    args.num_threads = 16

    # First test without filename replacing
    remove_old_files(database_helper)
    config.filename_replacing = False
    request_helper.make_course_paths()

    content_to_download = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)

    course_downloader = CourseDownloader(user)
    course_downloader.start()

    for item in content_to_download:
        assert os.path.exists(item.path)
        assert os.stat(item.path).st_size == item.size

    # Now test with filename replacing
    remove_old_files(database_helper)
    monkeypatch.undo()
    config.filename_replacing = True
    request_helper.make_course_paths()

    content_to_download = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)

    course_downloader.start()

    allowed_chars = set(string.ascii_letters + string.digits + ".")
    for item in content_to_download:
        assert os.path.exists(item.path)
        assert os.stat(item.path).st_size == item.size
        # The full path only consists of allowed chars
        assert all(c for item in Path(item.path).parts[1:] for c in item if c not in allowed_chars)

    # Now check if deleting the filetable and rediscovering works
    prev_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}

    dupl = defaultdict(list)
    for item in content_to_download:
        dupl[item.size].append(item)

    not_downloaded = [item for row in dupl.values() for item in row if len(row) > 1]

    # TODO
    # for item in not_downloaded:
    #     try:
    #         prev_ids.remove(item.file_id)
    #     except KeyError:
    #         pass

    monkeypatch.setattr("builtins.input", lambda _=None: "n")
    database_helper.delete_file_table()
    restore_database_state(request_helper)

    # Now check if everything is restored (except `possible_duplicates`)
    recovered_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}

    assert prev_ids.difference(recovered_ids) == set()


def sample_files(files: List[PreMediaContainer], num: int) -> List[Path]:
    sizes = {item.size for item in files}
    new_files = [item for item in Path(path()).rglob("*") if item.is_file() and item.stat().st_size in sizes]
    random.shuffle(files)

    return new_files[:num]


def get_checksums_of_files(files: List[Path]) -> List[str]:
    return [calculate_local_checksum(item) for item in files]


def test_move_files(database_helper: DatabaseHelper, request_helper: RequestHelper, monkeypatch: Any) -> None:
    content_to_download = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)
    dupl = defaultdict(list)
    for container in content_to_download:
        dupl[container.size].append(container)

    possible = [item for row in dupl.values() for item in row if len(row) == 1]

    the_files = sample_files(possible, 10)
    new_names = []
    new_files = []
    checksums = get_checksums_of_files(the_files)

    for i, item in enumerate(the_files):
        name, ext = os.path.splitext(item.name)
        new_name = name + "_UwU" + ext
        new_names.append(new_name)
        new_files.append(os.path.join(item.parent, new_name))
        item.rename(os.path.join(item.parent, new_name))

    the_files.insert(0, Path("/home/emily/testisisdl/SoSe2021Algorithmentheorie/onlineTutorium2.pdf"))
    monkeypatch.setattr("builtins.input", lambda _=None: "n")
    database_helper.delete_file_table()
    restore_database_state(request_helper)

    for csum, new_name in zip(checksums, new_names):
        assert database_helper.get_name_by_checksum(csum)

    for file in new_files:
        os.unlink(file)

    database_helper.delete_file_table()
    restore_database_state(request_helper)
    delete_missing_files_from_database(request_helper)
    for csum in checksums:
        assert database_helper.get_name_by_checksum(csum) is None
