#!/usr/bin/env python3
from __future__ import annotations

import enum
import mimetypes
import os
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from multiprocessing import cpu_count
from pathlib import Path
from typing import List, Tuple, Optional, Dict, DefaultDict, Set, Union

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, MediaContainer
from isisdl.backend.status import RequestHelperStatus, Status
from isisdl.settings import database_file_location, lock_file_location, enable_multithread, log_file_location
from isisdl.utils import path, calculate_local_checksum, database_helper, sanitize_name, do_ffprobe, get_input, MediaType, HumanBytes

_checksum_cache: Dict[Path, str] = {}


def delete_missing_files_from_database(helper: RequestHelper) -> None:
    checksums = database_helper.get_checksums_per_course()

    for course in helper._courses:
        if course.course_id not in checksums:
            continue

        for file in course.path().rglob("*"):
            if file.is_file():
                try:
                    checksum = _checksum_cache[file]
                except KeyError:
                    checksum = calculate_local_checksum(file)

                try:
                    checksums[course.course_id].remove(checksum)
                except KeyError:
                    pass

    count = 0
    for row in checksums.values():
        for item in row:
            database_helper.delete_file_by_checksum(item)
            count += 1

    print(f"\nDropped {count} entries from the database to be re-downloaded.")


class FileStatus(enum.Enum):
    to_dump = 0
    unchanged = 1
    corrupted = 2


not_considered_files = {
    path(database_file_location),
    path(lock_file_location),
    path(log_file_location)
}


def restore_file(
        file: Path, filename_mapping: Dict[Path, MediaContainer], files_for_course: Dict[Path, DefaultDict[int, List[MediaContainer]]], checksums: Set[str], status: Optional[Status] = None
) -> Tuple[Optional[FileStatus], Union[Path, MediaContainer]]:
    try:
        if file in not_considered_files:
            return None, file
        if not os.path.exists(file):
            return None, file

        if os.path.isdir(file):
            return None, file

        checksum = calculate_local_checksum(file)
        _checksum_cache[file] = checksum

        # TODO: Also dump the new meta info about the file. This would require a dict from checksum to MediaContainer
        if checksum in checksums:
            return FileStatus.unchanged, file

        # Adapt the size if the attribute is existent
        file_size = file.stat().st_size
        if file_size == 0:
            return None, file

        # Video files should not be corrupted
        file_type = mimetypes.guess_type(file.name)[0]
        if file_type is not None and file_type.startswith("video"):
            if (probe := do_ffprobe(file)) is None:
                return FileStatus.corrupted, file
            else:
                try:
                    file_size = probe['format']['tags']["previous_size"]
                except KeyError:
                    pass

        # First heuristic: File path
        possible = filename_mapping.get(file, None)
        if possible is not None and possible.size == file_size:
            possible.path = file
            possible.checksum = checksum

            return FileStatus.to_dump, possible

        # Second heuristic: File size
        for course, files in files_for_course.items():
            if str(course) in str(file):
                break
        else:
            return FileStatus.corrupted, file

        possible_files = files[file_size]
        if len(possible_files) == 1:
            possible = possible_files[0]
        else:
            # If there are multiple use the file name as a last resort to differentiate them
            possible = next((item for item in possible_files if sanitize_name(item._name, False) == file.name), None)

        if possible is not None and possible.size == file_size:
            possible.path = file
            possible.checksum = checksum

            return FileStatus.to_dump, possible

        return FileStatus.corrupted, file

    finally:
        if status is not None:
            status.done()


def restore_database_state(_content: Dict[MediaType, List[MediaContainer]], helper: RequestHelper, status: Optional[Status] = None) -> None:
    content = [item for row in list(item for item in _content.values()) for item in row]
    filename_mapping = {file.path: file for file in content}
    checksums = database_helper.get_checksums()
    files_for_course: Dict[Path, DefaultDict[int, List[MediaContainer]]] = {course.path(): defaultdict(list) for course in helper.courses}

    course_id_path_mapping = {course.course_id: course.path() for course in helper.courses}

    for container in content:
        files_for_course[course_id_path_mapping[container.course.course_id]][container.size].append(container)
        for link in container._links:
            files_for_course[course_id_path_mapping[container.course.course_id]][link.size].append(container)
            filename_mapping[link.path] = link

    _files = list(path().rglob("*"))
    random.shuffle(_files)

    if enable_multithread:
        with ThreadPoolExecutor(cpu_count()) as ex:
            files = list(ex.map(restore_file, _files, repeat(filename_mapping), repeat(files_for_course), repeat(checksums), repeat(status)))
    else:
        files = [restore_file(file, filename_mapping, files_for_course, checksums, status) for file in _files]

    database_helper.add_pre_containers([file[1] for file in files if file[0] == FileStatus.to_dump and isinstance(file[1], MediaContainer)])

    if status is not None:
        status.stop()

    num_recovered, num_unchanged, num_corrupted = 0, 0, 0
    size_recovered, size_unchanged, size_corrupted = 0, 0, 0
    corrupted_files: Set[Path] = set()
    for item in files:
        if item[0] is None:
            pass

        elif item[0] == FileStatus.corrupted and isinstance(item[1], Path):
            num_corrupted += 1
            size_corrupted += item[1].stat().st_size
            corrupted_files.add(item[1])

        elif item[0] == FileStatus.to_dump:
            num_recovered += 1
            if isinstance(item[1], Path):
                size_recovered += item[1].stat().st_size
            else:
                size_recovered += item[1].size

        elif item[0] == FileStatus.unchanged:
            num_unchanged += 1
            if isinstance(item[1], Path):
                size_unchanged += item[1].stat().st_size
            else:
                size_unchanged += item[1].size

        else:
            assert False

    max_len = max(len(str(item)) for item in [num_recovered, num_unchanged, num_corrupted])
    print(f"I have achieved the following:\n\n"
          f"Recovered files: {str(num_recovered).rjust(max_len)}, {HumanBytes.format_pad(size_recovered)}\n"
          f"Unchanged files: {str(num_unchanged).rjust(max_len)}, {HumanBytes.format_pad(size_unchanged)}\n"
          f"Corrupted files: {str(num_corrupted).rjust(max_len)}, {HumanBytes.format_pad(size_corrupted)}")

    if num_corrupted == 0:
        return

    if num_corrupted < 50:
        print("\n\nThe following files are corrupted / not recognized:\n\n" + "\n".join(str(item) for item in sorted(corrupted_files)))
        print("Do you want me to delete them? [y/n]")
    else:
        print(f"Do you want me to bulk delete all {num_corrupted} corrupted files? [y/n]")

    choice = get_input({"y", "n"})
    if choice == "n":
        return

    for file in corrupted_files:
        file.unlink()


def main() -> None:
    if not database_helper.filetable_exists() and not any(file not in not_considered_files and file.is_file() for file in path().rglob("*")):
        return

    user = get_credentials()

    with RequestHelperStatus() as status:
        helper = RequestHelper(user, status)
        content = helper.download_content(status)

    with Status("Discovering files", len(list(Path(path()).rglob("*")))) as status:
        restore_database_state(content, helper, status)

    delete_missing_files_from_database(helper)
