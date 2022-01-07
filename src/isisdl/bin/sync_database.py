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
from isisdl.settings import course_dir_location, enable_multithread, sync_database_num_threads, is_testing
from isisdl.backend.utils import path, logger, calculate_local_checksum, database_helper, get_input, config_helper, calculate_online_checksum_file


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
    print(f"Deleted {num} entr{'ies' if num == 1 else 'y'} from the database.")


def prep_container_and_dump(container: PreMediaContainer, file: Path) -> None:
    container.location, container.name = os.path.split(file)
    container.checksum = calculate_local_checksum(file)

    container.dump()


said_text = False


def restore_database_state(helper: RequestHelper, check_every_file: bool) -> None:
    files_to_download: Dict[Path, List[PreMediaContainer]] = defaultdict(list)

    assert helper.session is not None
    already_checked = 0

    for course in helper.courses:
        available_videos = course.download_videos(helper.session)
        available_documents = course.download_documents(helper)

        videos, documents = defaultdict(list), defaultdict(list)
        for item in available_videos:
            videos[item.size].append(item)

        for item in available_documents:
            documents[item.size].append(item)

        def corrupted_file_prompt(file: Path) -> None:
            global said_text
            if check_every_file:
                if said_text is False:
                    print("I've found the following corrupted files.\nIf you know that I've downloaded it go ahead and delete them."
                          "\n\n(This message is here since you have selected that there are other files I have not downloaded)\n\n")
                    said_text = True

                print(file.as_posix())
            else:
                file.unlink()

        for file in Path(course.path()).rglob("*"):
            if not os.path.isfile(file):
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

            elif len(possible) == 1 and not check_every_file:
                prep_container_and_dump(possible[0], file)
                already_checked += 1

            else:
                files_to_download[file].extend(possible)

    def check_multiple(file: Path, containers: List[PreMediaContainer]) -> int:
        assert helper.session is not None

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
            nums = list(ex.map(check_multiple, *zip(*list(files_to_download.items()))))

    else:
        nums = [check_multiple(file, containers) for file, containers in files_to_download.items()]

    if files_to_download:
        print(f"No unrecognized files (checked {sum(nums) + already_checked})")

    else:
        print(f"I have recovered {sum(nums) + already_checked} / {len(files_to_download) + already_checked} files.")

        if sum(nums) != len(files_to_download):
            print("The others have to be downloaded again.")


def main() -> None:
    prev_asked = config_helper.get_other_files_in_working_location()
    if prev_asked is None:
        choice = get_input(f"Are there other files - which I have not downloaded - in {path()}? [y/n] ", {"y", "n"})
        if choice == "y":
            print("This is going to greatly slow down the process of synchronizing the database.")
        else:
            print("Nice. This will greatly speed up the process of synchronizing the database.")

        second_choice = get_input("Do you want me to remember this option? [y/n] ", {"y", "n"})
        if second_choice == "y":
            config_helper.set_other_files_in_working_location(choice)
    else:
        choice = prev_asked

    user = get_credentials()
    request_helper = RequestHelper(user)

    restore_database_state(request_helper, choice == "y")
    delete_missing_files_from_database()


if __name__ == '__main__':
    main()
