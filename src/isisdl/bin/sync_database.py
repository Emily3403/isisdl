#!/usr/bin/env python3
from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path
from typing import List, Tuple

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer
from isisdl.backend.utils import path, calculate_local_checksum, database_helper
from isisdl.settings import is_autorun


def remove_corrupted_prompt(files: List[Path]) -> None:
    if not files:
        return

    print("I could not recognize the following files:\n" + "\n".join(item.as_posix() for item in files))
    print("\nDo you want me to delete them? [y/n]")
    choice = input()
    if choice == "n":
        return
    if choice != "y":
        print("I am going to interpret this as a no!")
        return

    for file in files:
        file.unlink()


def delete_missing_files_from_database(helper: RequestHelper) -> None:
    _checksums = database_helper.get_checksums_per_course()
    checksums = _checksums.copy()

    corrupted_files = []

    for course in helper.courses:
        if course.name not in _checksums:
            continue

        for file in Path(path(course.path())).rglob("*"):
            if file.is_file():
                try:
                    checksums[course.name].remove(calculate_local_checksum(file))
                except KeyError:
                    corrupted_files.append(file)

    for row in checksums.values():
        for item in row:
            database_helper.delete_by_checksum(item)

    num = sum(len(row) for row in checksums.values())
    print(f"Deleted {num} entr{'ies' if num != 1 else 'y'} from the database to be re-downloaded.")

    remove_corrupted_prompt(corrupted_files)


def restore_database_state(helper: RequestHelper) -> None:
    all_files = helper.download_content()
    corrupted_files = []
    recovered_containers: List[Tuple[PreMediaContainer, Path]] = []

    num_recovered_files = 0

    s = time.perf_counter()
    for course in helper.courses:
        files_for_course = defaultdict(list)
        for container in all_files:
            if container.course_id == course.course_id:
                files_for_course[container.size].append(container)

        for file in Path(course.path()).rglob("*"):
            if not os.path.isfile(file):
                continue

            if database_helper.get_name_by_checksum(calculate_local_checksum(file)) is not None:
                continue

            possible = files_for_course[file.stat().st_size]

            if len(possible) != 1:
                corrupted_files.append(file)
                continue

            recovered_containers.append((possible[0], file))
            num_recovered_files += 1

    final_containers = []
    for container, file in recovered_containers:
        container.location, container.name = file.parent.as_posix(), file.name
        container.checksum = calculate_local_checksum(file)
        final_containers.append(container)

    database_helper.add_pre_containers(final_containers)

    print(f"{time.perf_counter() - s:.3f}")

    total_num = len([item for course in helper.courses for item in Path(course.path()).rglob("*") if item.is_file()])
    if num_recovered_files == 0:
        print(f"No unrecognized files (checked {total_num})")

    else:
        print(f"I have recovered {num_recovered_files} / {total_num} possible files.")

    remove_corrupted_prompt(corrupted_files)


def main() -> None:
    user = get_credentials()
    request_helper = RequestHelper(user)

    database_helper.delete_file_table()
    restore_database_state(request_helper)
    delete_missing_files_from_database(request_helper)


if __name__ == "__main__":
    main()
