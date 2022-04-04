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
from typing import List, Tuple, Optional, Dict, DefaultDict

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer
from isisdl.backend.status import SyncStatus, RequestHelperStatus
from isisdl.backend.utils import path, calculate_local_checksum, database_helper, sanitize_name, do_ffprobe


# TODO: Check how long this takes
def delete_missing_files_from_database(helper: RequestHelper) -> None:
    checksums = database_helper.get_checksums_per_course()

    for course in helper.courses:
        if course.course_id not in checksums:
            continue

        for file in Path(path(course.path())).rglob("*"):
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
        file: Path, filename_mapping: Dict[str, PreMediaContainer], files_for_course: Dict[str, DefaultDict[int, List[PreMediaContainer]]], status: Optional[SyncStatus] = None
) -> Tuple[Optional[FileStatus], Path]:
    try:
        if not os.path.exists(file):
            return None, file

        if os.path.isdir(file):
            return None, file

        if database_helper.does_checksum_exist(calculate_local_checksum(file)):
            return FileStatus.unchanged, file

        def dump_file(possible: Optional[PreMediaContainer]) -> bool:
            if possible is not None and possible.size == file_size:
                possible.location = str(file)
                possible.checksum = calculate_local_checksum(file)
                possible.dump()
                return True

            return False

        # Adapt the size if the attribute is existent
        file_size = file.stat().st_size
        if (probe := do_ffprobe(str(file))) is not None:
            try:
                file_size = probe['format']['tags']["previous_size"]
            except KeyError:
                pass

        # Video files should not be corrupted
        file_type = mimetypes.guess_type(file.name)[0]
        if file_type is not None and file_type.startswith("video") and probe is None:
            return FileStatus.corrupted, file

        # First heuristic: File name
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


def restore_database_state(content: List[PreMediaContainer], helper: RequestHelper, status: Optional[SyncStatus] = None) -> None:
    filename_mapping = {file.path: file for file in content}
    files_for_course: Dict[str, DefaultDict[int, List[PreMediaContainer]]] = {course.path(): defaultdict(list) for course in helper.courses}

    course_id_path_mapping = {course.course_id: course.path() for course in helper.courses}

    for file in content:
        files_for_course[course_id_path_mapping[file.course_id]][file.size].append(file)

    with ThreadPoolExecutor(cpu_count() * 2) as ex:
        files = list(ex.map(get_it, Path(path()).rglob("*"), repeat(filename_mapping), repeat(files_for_course), repeat(status)))

    num_recovered, num_unchanged, num_corrupted = 0, 0, 0
    for item in files:
        if item[0] is None:
            pass
        elif item[0] == FileStatus.corrupted:
            num_corrupted += 1
        elif item[0] == FileStatus.recovered:
            num_recovered += 1
        elif item[0] == FileStatus.unchanged:
            num_unchanged += 1
        else:
            assert False

    print(f"Recovered: {num_recovered}\nUnchanged: {num_unchanged}\nCorrupted: {num_corrupted}")

    # for course in helper.courses:

    # if num_recovered_files == total_num:
    #     print(f"No unrecognized files (checked {total_num})")
    #
    # else:
    #     print(f"I have recovered {num_recovered_files} / {total_num} possible files.")
    #
    # print("\n\nThe following files are corrupted / not recognized:\n\n" + "\n".join(str(item) for item in sorted(corrupted_files)))
    # print("\nDo you want me to delete them? [y/n]")
    # choice = input()
    # if choice == "n":
    #     return
    # if choice != "y":
    #     print("I am going to interpret this as a no!")
    #     return
    #
    # for file in corrupted_files:
    #     file.unlink()


def main() -> None:
    user = get_credentials()

    with RequestHelperStatus() as status:
        helper = RequestHelper(user, status)
        content = helper.download_content(status)

    with SyncStatus(len(list(Path(path()).rglob("*")))) as status:
        restore_database_state(content, helper, status)

    # delete_missing_files_from_database(helper)
