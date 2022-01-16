#!/usr/bin/env python3
from __future__ import annotations

import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Tuple, Dict

from pymediainfo import MediaInfo

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer
from isisdl.backend.utils import path, calculate_local_checksum, database_helper, calculate_online_checksum_file
from isisdl.settings import course_dir_location, enable_multithread, sync_database_num_threads


def delete_missing_files_from_database() -> None:
    checksums = database_helper.get_checksums_per_course()

    for course in os.listdir(path(course_dir_location)):
        for file in Path(path(course_dir_location, course)).rglob("*"):
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
    print(f"Deleted {num} corruped entr{'ies' if num != 1 else 'y'} from the database to be redownloaded.")


def prep_container_and_dump(container: PreMediaContainer, file: Path) -> bool:
    container.location, container.name = os.path.split(file)
    container.checksum = calculate_local_checksum(file)

    return container.dump()


said_text = False


def restore_database_state(helper: RequestHelper) -> None:
    files_to_download: Dict[Path, List[PreMediaContainer]] = defaultdict(list)

    added_num_step_1 = 0

    # TODO: Threads

    for course in helper.courses:
        available_videos = course.download_videos(helper.session)
        available_documents = course.download_documents(helper)
        available_documents.extend(helper.download_mod_assign())

        videos, documents = defaultdict(list), defaultdict(list)
        for item in available_videos:
            videos[item.size].append(item)

        for item in available_documents:
            documents[item.size].append(item)

        def corrupted_file_prompt(file: Path) -> None:
            global said_text
            if said_text is False:
                print("I've found the following corrupted files.\nIf you know that I've downloaded it go ahead and delete them.")
                said_text = True

            print(file.as_posix())

        for file in Path(course.path()).rglob("*"):
            if not os.path.isfile(file):
                continue

            if database_helper.get_name_by_checksum(calculate_local_checksum(file)) is not None:
                continue

            possible: List[PreMediaContainer]
            if os.path.splitext(file.name)[1] == ".mp4":
                info = MediaInfo.parse(file)
                if info.tracks[0].duration is None:
                    corrupted_file_prompt(file)
                    continue

                possible = videos[int(info.tracks[0].duration / 1000)]

            else:
                possible = documents[file.stat().st_size]

            if len(possible) == 0:
                corrupted_file_prompt(file)

            elif len(possible) == 1:
                added_num_step_1 += not prep_container_and_dump(possible[0], file)

            else:
                files_to_download[file].extend(possible)

    def check_multiple(file: Path, containers: List[PreMediaContainer]) -> int:
        checksums: Dict[str, Tuple[int, PreMediaContainer]] = {}
        for item in containers:
            checksum, size = item.calculate_online_checksum(helper.session)
            checksums[checksum] = size, item

        valid_files = []
        for checksum, (size, item) in checksums.items():
            if calculate_online_checksum_file(file, size) == checksum:
                valid_files.append(item)

        if len(valid_files) == 0:
            return 0

        elif len(valid_files) > 1:
            # Two files with same checksum.
            # Since there is no heuristic (aside from filename) that is good enough to differentiate these files
            # they are completely ignored.
            return 0

        prep_container_and_dump(valid_files[0], file)

        return 1

    if enable_multithread:
        with ThreadPoolExecutor(sync_database_num_threads) as ex:
            added_num_step_2 = sum(list(ex.map(check_multiple, *zip(*list(files_to_download.items())))))

    else:
        added_num_step_2 = sum([check_multiple(file, containers) for file, containers in files_to_download.items()])

    recovered_num = added_num_step_1 + added_num_step_2
    total_num = len([item for course in helper.courses for item in Path(course.path()).rglob("*") if item.is_file()])
    if recovered_num == 0:
        print(f"No unrecognized files (checked {total_num})")

    else:
        print(f"I have recovered {recovered_num} / {total_num} possible files.")


def main() -> None:
    user = get_credentials()
    request_helper = RequestHelper(user)

    restore_database_state(request_helper)
    delete_missing_files_from_database()


# TODO: Testing what happens when randomly inserting files

if __name__ == "__main__":
    main()
