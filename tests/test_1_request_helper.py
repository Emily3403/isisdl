import os
import random
import shutil
import string
from typing import Any, List, Dict

import pytest

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import RequestHelper, MediaContainer, CourseDownloader
from isisdl.settings import testing_download_sizes, env_var_name_username, env_var_name_password, database_file_location, lock_file_location, log_file_location
from isisdl.utils import User, config, calculate_local_checksum, MediaType, path, startup, database_helper


def remove_old_files() -> None:
    for item in os.listdir(path()):
        if item not in {database_file_location, database_file_location + "-journal", lock_file_location, log_file_location}:
            shutil.rmtree(path(item))

    startup()
    config.__init__()  # type: ignore
    database_helper.__init__()  # type: ignore
    config.filename_replacing = True


def test_remove_old_files() -> None:
    remove_old_files()


def test_database_helper(database_helper: DatabaseHelper) -> None:
    assert database_helper is not None
    database_helper.delete_file_table()
    database_helper.delete_config()

    assert all(bool(item) is False for item in database_helper.get_state().values())


def test_request_helper(request_helper: RequestHelper) -> None:
    assert request_helper is not None
    assert request_helper._instance is not None
    assert request_helper._instance_init is True
    assert request_helper.session is not None

    assert len(request_helper._courses) > 5
    assert len(request_helper.courses) > 5


def chop_down_size(files_type: Dict[MediaType, List[MediaContainer]]) -> Dict[MediaType, List[MediaContainer]]:
    ret_files: Dict[MediaType, List[MediaContainer]] = {typ: [] for typ in MediaType}

    for (typ, files), ret in zip(files_type.items(), ret_files.values()):
        if not files or sum(file.size for file in files) == 0:
            continue

        files.sort()
        cur_size = 0
        max_size = testing_download_sizes[typ.value]

        while True:
            choice = random.choices(files, list(range(len(files))), k=1)[0]
            if cur_size + choice.size > max_size:
                break

            ret.append(choice)
            cur_size += choice.size

    return ret_files


def get_content_to_download(request_helper: RequestHelper, monkeypatch: Any) -> Dict[MediaType, List[MediaContainer]]:
    con = request_helper.download_content()
    content = chop_down_size(con)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None, __=None: content)

    return content


@pytest.mark.skip(reason="Currently disabled, will not be fixed until 2.0")
def test_normal_download(request_helper: RequestHelper, database_helper: DatabaseHelper, user: User, monkeypatch: Any) -> None:
    request_helper.make_course_paths()

    os.environ[env_var_name_username] = os.environ["ISISDL_ACTUAL_USERNAME"]
    os.environ[env_var_name_password] = os.environ["ISISDL_ACTUAL_PASSWORD"]

    content = get_content_to_download(request_helper, monkeypatch)

    # The main entry point
    CourseDownloader().start()

    allowed_chars = set(string.ascii_letters + string.digits + ".")
    bad_urls = set(database_helper.get_bad_urls())

    # Now check if everything was downloaded successfully
    for container in [item for row in content.values() for item in row]:
        assert container.path.exists()
        assert all(c for item in container.path.parts[1:] for c in item if c not in allowed_chars)

        if container.media_type != MediaType.corrupted:
            assert container.size != 0 and container.size != -1
            assert container.size == container.current_size
            assert container.path.stat().st_size == container.size
            assert container.checksum == calculate_local_checksum(container.path)

            dump_container = MediaContainer.from_dump(container.url, container.course)
            assert isinstance(dump_container, MediaContainer)
            assert container == dump_container

        else:
            assert container.size == 0
            assert container.current_size is None
            assert container.url in bad_urls
            assert container.path.stat().st_size == 0
