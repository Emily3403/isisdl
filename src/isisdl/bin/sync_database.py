#!/usr/bin/env python3
from __future__ import annotations

import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Tuple, Dict

from pymediainfo import MediaInfo

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer, Course
from isisdl.backend.utils import path, calculate_local_checksum, database_helper, calculate_online_checksum_file
from isisdl.settings import enable_multithread, sync_database_num_threads, is_autorun


def delete_missing_files_from_database() -> None:
    checksums = database_helper.get_checksums_per_course()

    for course in os.listdir(path()):
        for file in Path(path(course)).rglob("*"):
            if file.is_file():
                correct_course = checksums[course]
                try:
                    correct_course.remove(calculate_local_checksum(file))
                except KeyError:
                    pass

    for row in checksums.values():
        for item in row:
            database_helper.delete_by_checksum(item)

    num = sum(len(row) for row in checksums.values())
    print(f"Deleted {num} entr{'ies' if num != 1 else 'y'} from the database to be re-downloaded.")


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

    if not corrupted_files:
        return

    print("I could not recognize the following files:\n(If the file sizes are equal between two files I cannot tell them apart)\n\n" + "\n".join(item.as_posix() for item in corrupted_files))
    print("\nDo you want me to delete them? [y/n]")
    choice = input()
    if choice == "n":
        return
    if choice != "y":
        print("I am going to interpret this as a no!")
        return

    for file in corrupted_files:
        file.unlink()


def main() -> None:
    s = time.perf_counter()
    delete_missing_files_from_database()
    print(f"{time.perf_counter() - s:.3f}")


    if is_autorun:
        exit(1)

    user = get_credentials()
    request_helper = RequestHelper(user)

    database_helper.delete_file_table()
    restore_database_state(request_helper)

    delete_missing_files_from_database()


# TODO: Testing what happens when randomly inserting files

if __name__ == "__main__":
    main()
