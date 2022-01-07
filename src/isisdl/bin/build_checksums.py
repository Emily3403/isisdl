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
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer
from isisdl.share.settings import course_dir_location, working_dir_location, enable_multithread, sync_database_num_threads
from isisdl.share.utils import path, logger, calculate_local_checksum, database_helper, get_input, config_helper, calculate_online_checksum_file


# TODO: Assert sizes
def database_subset_files() -> None:
    s = time.perf_counter()
    checksums = database_helper.get_checksums_per_course()

    for course in os.listdir(path(course_dir_location)):
        for file in Path(path(course_dir_location, course)).rglob("*"):
            if file.is_file():
                try:
                    checksums[course].remove(calculate_local_checksum(file.as_posix()))
                except KeyError:
                    pass

    missed_files = [(item, course) for course, row in checksums.items() for item in row]

    missed_file_names: List[Tuple[str, str]] = [(database_helper.get_name_by_checksum(item), course) for item, course in missed_files]  # type: ignore

    if missed_file_names:
        max_file_len = max(len(item[0]) for item in missed_file_names)

        logger.warning("Noticied missing files:\n" + "\n".join(f"{item.ljust(max_file_len)} → {course}" for item, course in missed_file_names))
        logger.warning("I am updating the database accordingly.")

    for item, _ in missed_files:
        database_helper.delete_by_file_id(item)

    logger.info(f"Successfully built all checksums in {time.perf_counter() - s:.3f}s.")


def prep_container_and_dump(container: PreMediaContainer, file: Path) -> None:
    container.location, container.name = os.path.split(file)
    container.checksum = calculate_local_checksum(file.as_posix())

    container.dump()


def check_file_equal(file: Path, online_file: PreMediaContainer) -> bool:
    return True
    pass


def files_subset_database(helper: RequestHelper, check_every_file: bool) -> None:
    files_to_download: Dict[Path, List[PreMediaContainer]] = defaultdict(list)
    file_to_course_mapping = defaultdict(list)
    file_to_posix_mapping: Dict[str, str] = {}

    assert helper.session is not None

    for course in helper.courses:
        available_videos = course.download_videos(helper.session)
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
            else:
                possible = documents[file.stat().st_size]

            if len(possible) == 0:
                assert False

            elif len(possible) == 1 and not check_every_file:
                prep_container_and_dump(possible[0], file)

            else:
                files_to_download[file].extend(possible)

    def update_container(file: Path, containers: List[PreMediaContainer]) -> int:
        assert helper.session is not None

        file_checksum = calculate_online_checksum_file(file.as_posix())
        checksums = {item: item.calculate_online_checksum(helper.session) for item in containers}
        checksums = {k: v for k, v in checksums.items() if v == file_checksum}

        if len(checksums) == 0:
            assert False

        elif len(checksums) > 1:
            # Two files with same checksum.
            # Since there is no heuristic (aside from filename) that is good enough to differentiate these files
            # they are completely ignored.
            return 0

        prep_container_and_dump(list(checksums.keys())[0], file)

        return 1

    if enable_multithread:
        with ThreadPoolExecutor(sync_database_num_threads) as ex:
            nums = list(ex.map(update_container, *zip(*list(files_to_download.items()))))

    else:
        nums = [update_container(file, containers) for file, containers in files_to_download.items()]

    logger.info(f"I have recovered {sum(nums)} / {len(files_to_download)} files.")
    pass


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

    choice = "y"
    user = get_credentials()
    request_helper = RequestHelper(user)

    files_subset_database(request_helper, choice == "y")
    database_subset_files()


if __name__ == '__main__':
    main()
