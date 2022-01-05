#!/usr/bin/env python3
from __future__ import annotations
import os
import time
from collections import defaultdict
from pathlib import Path, PosixPath
from typing import List, Tuple, Dict

from pymediainfo import MediaInfo

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer
from isisdl.share.settings import download_dir_location, working_dir_location
from isisdl.share.utils import path, logger, calculate_checksum, database_helper, User, get_input, config_helper


def database_subset_files() -> None:
    s = time.perf_counter()
    checksums = database_helper.get_checksums_per_course()

    for course in os.listdir(path(download_dir_location)):
        for file in Path(path(download_dir_location, course)).rglob("*"):
            if file.is_file():
                try:
                    checksums[course].remove(calculate_checksum(file.as_posix()))
                except KeyError:
                    pass

    missed_files = [(item, course) for course, row in checksums.items() for item in row]

    missed_file_names: List[Tuple[str, str]] = [(database_helper.get_name_by_checksum(item), course) for item, course in missed_files]  # type: ignore

    if missed_file_names:
        max_file_len = max(len(item[0]) for item in missed_file_names)

        logger.warning("Noticied missing files:\n" + "\n".join(f"{item.ljust(max_file_len)} → {course}" for item, course in missed_file_names))
        logger.warning("I am updating the database accordingly.")

    for item, _ in missed_files:
        database_helper.delete_by_checksum(item)

    logger.info(f"Successfully built all checksums in {time.perf_counter() - s:.3f}s.")


def check_file_equal(file: Path, online_file: PreMediaContainer) -> bool:
    return True
    pass


def files_subset_database(helper: RequestHelper, check_every_file: bool) -> None:
    files_to_download: Dict[str, PreMediaContainer] = {}
    file_to_course_mapping = defaultdict(list)

    for course in helper.courses[2:3]:
        available_videos = course.download_videos(helper.sessions[0])
        available_documents = course.download_documents(helper)

        videos, documents = defaultdict(list), defaultdict(list)
        for item in available_videos:
            videos[item.size].append(item)

        for item in available_documents:
            documents[item.size].append(item)

        for file in Path(course.path()).rglob("*"):
            if not os.path.isfile(file):
                continue

            file_to_course_mapping[course].append(file)

            possible: List[PreMediaContainer]
            if os.path.splitext(file.name)[1] == ".mp4":
                info = MediaInfo.parse(file)
                possible = videos[int(info.tracks[0].duration / 1000)]
                if not possible:
                    assert False
            else:
                possible = documents[file.stat().st_size]

            if len(possible) == 0:
                continue

            elif len(possible) == 1 and not check_every_file:
                item = possible[0]
                item.checksum = calculate_checksum(file.as_posix())
                item.dump()

            else:
                files_to_download.update({item.file_id: item for item in possible})



    pass


def main() -> None:
    prev_asked = config_helper.get_other_files_in_working_location()
    if prev_asked is None:
        choice = get_input(f"Are there other files - which I have not downloaded - in {working_dir_location}? [y/n] ", {"y", "n"})
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

    files_subset_database(request_helper, choice == "y")
    database_subset_files()


if __name__ == '__main__':
    main()
