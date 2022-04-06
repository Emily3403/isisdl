import os
import random
import shutil
import string
from itertools import permutations
from pathlib import Path
from typing import Any, List, Dict, Set

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.request_helper import RequestHelper, MediaContainer, CourseDownloader, check_for_conflicts_in_files
from isisdl.utils import path, args, User, config, startup, database_helper, calculate_local_checksum, MediaType
from isisdl.settings import database_file_location, lock_file_location, testing_download_sizes, env_var_name_username, env_var_name_password


def remove_old_files() -> None:
    for item in os.listdir(path()):
        if item != database_file_location and item != lock_file_location:
            shutil.rmtree(path(item))

    startup()
    config.__init__()  # type: ignore
    database_helper.__init__()  # type: ignore
    return


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

        while cur_size < max_size:
            choice = random.choices(files, list(range(len(files))), k=1)[0]
            ret.append(choice)
            cur_size += choice.size

    return ret_files


def get_content_to_download(request_helper: RequestHelper) -> List[MediaContainer]:
    conflict_free = chop_down_size(request_helper.download_content())
    return [item for row in conflict_free.values() for item in row]


def test_normal_download(request_helper: RequestHelper, database_helper: DatabaseHelper, user: User, monkeypatch: Any) -> None:
    args.num_threads = 4

    # Test without filename replacing
    config.filename_replacing = True

    request_helper.make_course_paths()
    os.environ[env_var_name_username] = os.environ["ISISDL_ACTUAL_USERNAME"]
    os.environ[env_var_name_password] = os.environ["ISISDL_ACTUAL_PASSWORD"]

    content = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None, __=None: content)

    # The main entry point
    CourseDownloader().start()

    # Now check if everything was downloaded successfully
    allowed_chars = set(string.ascii_letters + string.digits + ".")

    for container in content:
        assert container.path.exists()
        assert container.size != 0 and container.size != -1
        assert all(c for item in container.path.parts[1:] for c in item if c not in allowed_chars)

        if container.media_type != MediaType.corrupted:
            assert container.path.stat().st_size == container.size
            assert container.checksum is not None

            dump_container = MediaContainer.from_dump(container.url)
            assert isinstance(dump_container, MediaContainer)
            assert calculate_local_checksum(container.path) == container.checksum == dump_container.checksum
            assert container == dump_container

        else:
            assert container.path.stat().st_size == 0

    # Now we do ...
    prev_urls: Set[str] = set()
    container_mapping = {item.url: item for item in content}
    for item in database_helper.get_state()["fileinfo"]:
        url = item[1]

        if url in container_mapping:
            container = container_mapping[url]
            restored = MediaContainer.from_dump(item[1])
            assert item[8] is not None
            assert isinstance(restored, MediaContainer)
            assert restored.checksum is not None
            assert container == restored
            prev_urls.update(url)

        else:
            # Not downloaded (yet), checksum should be None.
            assert item[8] is None
    #
    # dupl = defaultdict(list)
    # for item in content:
    #     dupl[item.size].append(item)

    # not_downloaded = [item for row in dupl.values() for item in row if len(row) > 1]

    # TODO
    # for item in not_downloaded:
    #     try:
    #         prev_ids.remove(item.file_id)
    #     except KeyError:
    #         pass
    #
    # monkeypatch.setattr("builtins.input", lambda _=None: "n")
    # database_helper.delete_file_table()
    # restore_database_state(request_helper.download_content(), request_helper)
    #
    # # Now check if everything is restored (except `possible_duplicates`)
    # recovered_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}
    #
    # assert prev_ids.difference(recovered_ids) == set()

# def sample_files(files: List[MediaContainer], num: int) -> List[Path]:
#     sizes = {item.size for item in files}
#     new_files = [item for item in Path(path()).rglob("*") if item.is_file() and item.stat().st_size in sizes]
#     random.shuffle(files)
#
#     return new_files[:num]
#
#
# def get_checksums_of_files(files: List[Path]) -> List[str]:
#     return [calculate_local_checksum(item) for item in files]
#
#
# def test_move_files(database_helper: DatabaseHelper, request_helper: RequestHelper, monkeypatch: Any) -> None:
#     content_to_download = get_content_to_download(request_helper)
#     monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)
#     dupl = defaultdict(list)
#     for container in content_to_download:
#         dupl[container.size].append(container)
#
#     possible = [item for row in dupl.values() for item in row if len(row) == 1]
#
#     the_files = sample_files(possible, 10)
#     new_names = []
#     new_files = []
#     checksums = get_checksums_of_files(the_files)
#
#     for i, item in enumerate(the_files):
#         name, ext = os.path.splitext(item.name)
#         new_name = name + "_UwU" + ext
#         new_names.append(new_name)
#         new_files.append(os.path.join(item.parent, new_name))
#         item.rename(os.path.join(item.parent, new_name))
#
#     the_files.insert(0, Path("/home/emily/testisisdl/SoSe2021Algorithmentheorie/onlineTutorium2.pdf"))
#     monkeypatch.setattr("builtins.input", lambda _=None: "n")
#     database_helper.delete_file_table()
#     restore_database_state(request_helper.download_content(), request_helper)
#
#     for csum, new_name in zip(checksums, new_names):
#         assert database_helper.get_name_by_checksum(csum)
#
#     for file in new_files:
#         os.unlink(file)
#
#     database_helper.delete_file_table()
#     restore_database_state(request_helper.download_content(), request_helper)
#     delete_missing_files_from_database(request_helper)
#     for csum in checksums:
#         assert database_helper.get_name_by_checksum(csum) is None
