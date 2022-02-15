#!/usr/bin/env python3
from __future__ import annotations

import mimetypes
import os
import time
from collections import defaultdict
from pathlib import Path
from threading import Thread
from typing import List, Tuple, Set, Optional

from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import print_log_messages
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer, pre_status
from isisdl.backend.utils import path, calculate_local_checksum, database_helper, is_h265, sanitize_name, acquire_file_lock_or_exit
from isisdl.settings import has_ffmpeg, status_time, status_progress_bar_resolution, is_first_time

corrupted_files: Set[Path] = set()


def remove_corrupted_prompt(files: Set[Path]) -> None:
    if not files:
        return

    print("\n\nThe following files are corrupted / not recognized:\n\n" + "\n".join(str(item) for item in sorted(files)))
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
    pre_status.stop()
    checksums = database_helper.get_checksums_per_course()

    global corrupted_files
    for course in helper.courses:
        if course.name not in checksums:
            continue

        for file in Path(path(course.path())).rglob("*"):
            if file.is_file():
                checksum = calculate_local_checksum(file)
                try:
                    checksums[course.name].remove(checksum)
                except KeyError:
                    pass

    for row in checksums.values():
        for item in row:
            database_helper.delete_by_checksum(item)


def restore_database_state(helper: RequestHelper) -> None:
    all_files = helper.download_content()
    pre_status.stop()
    sync_status = SyncStatus(len(all_files))
    print("\n")
    sync_status.start()

    global corrupted_files
    recovered_containers: List[Tuple[PreMediaContainer, Path]] = []

    num_recovered_files = 0

    for course in helper.courses:
        filename_mapping = {sanitize_name(item._name): item for item in all_files if item.course_id == course.course_id}
        files_for_course = defaultdict(list)
        for container in all_files:
            if container.course_id == course.course_id:
                files_for_course[container.size].append(container)

        for file in Path(course.path()).rglob("*"):
            sync_status.done_thing()
            if not os.path.isfile(file):
                continue

            if database_helper.get_name_by_checksum(calculate_local_checksum(file)) is not None:
                num_recovered_files += 1
                continue

            # First heuristic: File name
            possible = filename_mapping.get(file.name, None)
            file_is_h265: Optional[bool] = False
            if has_ffmpeg:
                file_type = mimetypes.guess_type(file.name)[0]
                if file_type is not None and file_type.startswith("video"):
                    file_is_h265 = is_h265(str(file))

            if file_is_h265 is None:
                corrupted_files.add(file)
                continue

            # The file size must only be the same when the coding is not h265
            if file_is_h265 is False:
                possible_lst = files_for_course[file.stat().st_size]
                if len(possible_lst) == 1:
                    possible = possible_lst[0]
                else:
                    possible = next((item for item in files_for_course[file.stat().st_size] if sanitize_name(item._name) == file.name), None)

                if possible is None:
                    corrupted_files.add(file)
                    continue

            # Second heuristic: File size
            if possible is None:
                size_possible = files_for_course[file.stat().st_size]
                if len(size_possible) != 1:
                    corrupted_files.add(file)
                    continue

                possible = size_possible[0]

            recovered_containers.append((possible, file))
            num_recovered_files += 1

    sync_status.stop()
    final_containers = []
    for container, file in recovered_containers:
        container.location, container._name = str(file.parent), file.name
        container.checksum = calculate_local_checksum(file)
        final_containers.append(container)

    database_helper.add_pre_containers(final_containers)

    total_num = len([item for course in helper.courses for item in Path(course.path()).rglob("*") if item.is_file()])
    print()
    if num_recovered_files == total_num:
        print(f"No unrecognized files (checked {total_num})")

    else:
        print(f"I have recovered {num_recovered_files} / {total_num} possible files.")


class SyncStatus(Thread):
    progress_bar = ["-", "\\", "|", "/"]

    def __init__(self, total_files: int) -> None:
        self.total_files = total_files
        self.i = 0
        self.num_done = 0
        self._running = True
        self.last_text_len = 0
        super().__init__(daemon=True)

    def add_total_files(self, total_files: int) -> None:
        self.total_files = total_files
        self.i = 0

    def done_thing(self) -> None:
        self.num_done += 1

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        time.sleep(status_time)
        while self._running:
            log_strings = ["Discovering files " + "." * self.i, ""]

            perc_done = int(self.num_done / self.total_files * status_progress_bar_resolution)
            log_strings.append(f"[{'█' * perc_done}{' ' * (status_progress_bar_resolution - perc_done)}]")
            if self._running:
                self.last_text_len = print_log_messages(log_strings, self.last_text_len)

            self.i = (self.i + 1) % len(self.progress_bar)
            time.sleep(status_time)


def _main() -> None:
    pre_status.start()
    user = get_credentials()
    request_helper = RequestHelper(user)

    restore_database_state(request_helper)
    delete_missing_files_from_database(request_helper)

    remove_corrupted_prompt(corrupted_files)


def main() -> None:
    acquire_file_lock_or_exit()
    if is_first_time:
        import isisdl.bin.config as config_run
        print("No database found. Running the config wizard ...\n\nPress Enter to continue\n")
        input()
        config_run.run_config_wizard()

    _main()


if __name__ == "__main__":
    main()
