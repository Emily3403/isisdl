#!/usr/bin/env python3
from __future__ import annotations

import enum
import mimetypes
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from multiprocessing import cpu_count
from pathlib import Path
from typing import List, Tuple, Optional, Dict, DefaultDict, Set

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, MediaContainer
from isisdl.backend.status import SyncStatus, RequestHelperStatus
from isisdl.settings import database_file_location, lock_file_location
from isisdl.utils import path, calculate_local_checksum, database_helper, sanitize_name, do_ffprobe, get_input


# TODO: Check how long this takes
def delete_missing_files_from_database(helper: RequestHelper) -> None:
    checksums = database_helper.get_checksums_per_course()

    for course in helper.courses:
        if course.course_id not in checksums:
            continue

        for file in course.path().rglob("*"):
            if file.is_file():
                checksum = calculate_local_checksum(file)
                try:
                    checksums[course.course_id].remove(checksum)
                except KeyError:
                    pass

    count = 0
    for row in checksums.values():
        for item in row:
            database_helper.delete_by_checksum(item)
            count += 1

    print(f"Dropped {count} entries from the database to be re-downloaded.")


class FileStatus(enum.Enum):
    recovered = 0
    unchanged = 1
    corrupted = 2


def get_it(
        file: Path, filename_mapping: Dict[str, MediaContainer], files_for_course: Dict[str, DefaultDict[int, List[MediaContainer]]], status: Optional[SyncStatus] = None
) -> Tuple[Optional[FileStatus], Path]:
    try:
        if file in {
            path(database_file_location),
            path(lock_file_location),
        }:
            return None, file
        if not os.path.exists(file):
            return None, file

        if os.path.isdir(file):
            return None, file

        if database_helper.does_checksum_exist(calculate_local_checksum(file)):
            return FileStatus.unchanged, file

        def dump_file(possible: Optional[MediaContainer]) -> bool:
            if possible is not None and possible.size == file_size:
                possible.path = file
                possible.checksum = calculate_local_checksum(file)
                possible.dump()
                return True

            return False

        # Adapt the size if the attribute is existent
        file_size = file.stat().st_size
        if (probe := do_ffprobe(file)) is not None:
            try:
                file_size = probe['format']['tags']["previous_size"]
            except KeyError:
                pass

        # Video files should not be corrupted
        file_type = mimetypes.guess_type(file.name)[0]
        if file_type is not None and file_type.startswith("video") and probe is None:
            return FileStatus.corrupted, file

        # First heuristic: File path
        possible = filename_mapping.get(str(file), None)
        if dump_file(possible):
            return FileStatus.recovered, file

        # Second heuristic: File size
        for course, files in files_for_course.items():
            if course in str(file):
                break
        else:
            return FileStatus.corrupted, file

        possible_files = files[file_size]
        if len(possible_files) == 1:
            possible = possible_files[0]
        else:
            # If there are multiple use the file name as a last resort to differentiate them
            possible = next((item for item in possible_files if sanitize_name(item._name) == file.name), None)

        if dump_file(possible):
            return FileStatus.recovered, file

        return FileStatus.corrupted, file

    finally:
        if status is not None:
            status.done()


def restore_database_state(content: List[MediaContainer], helper: RequestHelper, status: Optional[SyncStatus] = None) -> None:
    filename_mapping = {file.path: file for file in content}
    files_for_course: Dict[Path, DefaultDict[int, List[MediaContainer]]] = {course.path(): defaultdict(list) for course in helper.courses}

    course_id_path_mapping = {course.course_id: course.path() for course in helper.courses}

    for container in content:
        files_for_course[course_id_path_mapping[container.course.course_id]][container.size].append(container)

    with ThreadPoolExecutor(cpu_count() * 2) as ex:
        files = list(ex.map(get_it, Path(path()).rglob("*"), repeat(filename_mapping), repeat(files_for_course), repeat(status)))

    if status is not None:
        status.stop()

    num_recovered, num_unchanged, num_corrupted = 0, 0, 0
    corrupted_files: Set[Path] = set()
    for item in files:
        if item[0] is None:
            pass
        elif item[0] == FileStatus.corrupted:
            num_corrupted += 1
            corrupted_files.add(item[1])
        elif item[0] == FileStatus.recovered:
            num_recovered += 1
        elif item[0] == FileStatus.unchanged:
            num_unchanged += 1
        else:
            assert False

    print(f"Recovered: {num_recovered}\nUnchanged: {num_unchanged}\nCorrupted: {num_corrupted}")

    if num_corrupted == 0:
        return

    if num_corrupted < 50:
        print("\n\nThe following files are corrupted / not recognized:\n\n" + "\n".join(str(item) for item in sorted(corrupted_files)))
    else:
        print(f"There are {num_corrupted} files! ")

    print(f"\nDo you want me to{' bulk' if num_corrupted > 50 else ''} delete them? [y/n]")
    choice = get_input({"y", "n"})
    if choice == "n":
        return

    for file in corrupted_files:
        file.unlink()


def main() -> None:
    user = get_credentials()

    with RequestHelperStatus() as status:
        helper = RequestHelper(user, status)
        content = helper.download_content(status)

    with SyncStatus(len(list(Path(path()).rglob("*")))) as status:
        restore_database_state(content, helper, status)

    # delete_missing_files_from_database(helper)
