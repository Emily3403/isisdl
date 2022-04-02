#!/usr/bin/env python3
from __future__ import annotations

import enum
import mimetypes
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from multiprocessing import cpu_count
from pathlib import Path
from threading import Thread
from typing import List, Tuple, Optional, Dict, DefaultDict

from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import print_log_messages
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer, pre_status
from isisdl.backend.utils import path, calculate_local_checksum, database_helper, sanitize_name, acquire_file_lock_or_exit, do_ffprobe
from isisdl.settings import status_time, status_progress_bar_resolution, is_first_time


def delete_missing_files_from_database(helper: RequestHelper) -> None:
    pre_status.stop()
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


def get_it(file: Path, filename_mapping: Dict[str, PreMediaContainer], files_for_course: Dict[str, DefaultDict[int, List[PreMediaContainer]]], status: SyncStatus) -> Tuple[Optional[FileStatus], Path]:
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
        status.done_thing()


def restore_database_state(content: List[PreMediaContainer], helper: RequestHelper, status: SyncStatus) -> None:
    filename_mapping = {file.path: file for file in content}
    files_for_course: Dict[str, DefaultDict[int, List[PreMediaContainer]]] = {course.path(): defaultdict(list) for course in helper.courses}

    course_id_path_mapping = {course.course_id: course.path() for course in helper.courses}

    for file in content:
        files_for_course[course_id_path_mapping[file.course_id]][file.size].append(file)

    with ThreadPoolExecutor(cpu_count()) as ex:
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


# TODO: Syntactic sugar: define __exit__ and __enter__ for `with SyncStatus():`
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
    user = get_credentials()

    pre_status.start()
    helper = RequestHelper(user)
    content = helper.download_content()
    pre_status.stop()
    print()

    sync_status = SyncStatus(len(list(Path(path()).rglob("*"))))
    sync_status.start()
    restore_database_state(content, helper, sync_status)
    sync_status.stop()
    return

    # delete_missing_files_from_database(helper)


def main() -> None:
    acquire_file_lock_or_exit()
    if is_first_time:
        import isisdl.bin.config as config_run
        print("No database found. Running the config wizard ...\n\nPress Enter to continue\n")
        input()
        config_run.init_wizard()

    _main()


if __name__ == "__main__":
    main()
