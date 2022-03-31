#!/usr/bin/env python3
from __future__ import annotations

import mimetypes
import os
import time
from collections import defaultdict
from itertools import repeat
from multiprocessing import Pool, cpu_count
from pathlib import Path
from threading import Thread
from typing import List, Tuple, Set, Optional, Dict, Union

from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import print_log_messages
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer, pre_status
from isisdl.backend.utils import path, calculate_local_checksum, database_helper, is_h265, sanitize_name, acquire_file_lock_or_exit, do_ffprobe
from isisdl.settings import has_ffmpeg, status_time, status_progress_bar_resolution, is_first_time


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


def get_it(file: Path, filename_mapping: Dict[str, str], files_for_course) -> Union[Path, bool, None]:
    if not os.path.exists(file):
        return None

    if os.path.isdir(file):
        return None

    if database_helper.does_checksum_exist(calculate_local_checksum(file)):
        return True

    if file.stat().st_size == 0:
        return True

    # First heuristic: File name
    possible = filename_mapping.get(str(file), None)
    file_size = file.stat().st_size
    if (probe := do_ffprobe(str(file))) is not None:
        try:
            file_size = probe['format']['tags']["previous_size"]

        except KeyError:
            pass


    possible_lst = files_for_course[file.stat().st_size]
    if len(possible_lst) == 1:
        possible = possible_lst[0]
    else:
        possible = next((item for item in files_for_course[file.stat().st_size] if sanitize_name(item._name) == file.name), None)

    if possible is None:
        corrupted_files.add(file)

    return None

    file_is_h265: Optional[bool] = False
    if has_ffmpeg:
        file_type = mimetypes.guess_type(file.name)[0]
        if file_type is not None and file_type.startswith("video"):
            file_is_h265 = is_h265(str(file))

    if file_is_h265 is None:
        corrupted_files.add(file)

    # The file size must only be the same when the coding is not h265
    if file_is_h265 is False:
        possible_lst = files_for_course[file.stat().st_size]
        if len(possible_lst) == 1:
            possible = possible_lst[0]
        else:
            possible = next((item for item in files_for_course[file.stat().st_size] if sanitize_name(item._name) == file.name), None)

        if possible is None:
            corrupted_files.add(file)

    # Second heuristic: File size
    if possible is None:
        size_possible = files_for_course[file.stat().st_size]
        if len(size_possible) != 1:
            corrupted_files.add(file)

        possible = size_possible[0]

    recovered_containers.append((possible, file))
    num_recovered_files += 1
    return file






def restore_database_state(helper: RequestHelper) -> None:
    all_files = helper.download_content()
    sync_status = SyncStatus(len(all_files))
    sync_status.start()

    corrupted_files: Set[Path] = set()
    recovered_containers: List[Tuple[PreMediaContainer, Path]] = []

    num_recovered_files = 0

    filename_mapping = {file.path: file for file in all_files}

    files_for_course = defaultdict(list)
    # TODO: multithread this
    for container in all_files:
        if container.course_id == course.course_id:
            files_for_course[container.size].append(container)

    with Pool(cpu_count()) as ex:
        files = ex.starmap(get_it, zip(Path(path()).rglob("*"), repeat(filename_mapping)))

    # for course in helper.courses:




    sync_status.stop()
    final_containers = []
    for container, file in recovered_containers:
        container.location, container._name = str(file.parent), file.name
        container.checksum = calculate_local_checksum(file)
        final_containers.append(container)

    database_helper.add_pre_containers(final_containers)

    total_num = len([item for course in helper.courses for item in Path(course.path()).rglob("*") if item.is_file()])
    print("\n\n")
    if num_recovered_files == total_num:
        print(f"No unrecognized files (checked {total_num})")

    else:
        print(f"I have recovered {num_recovered_files} / {total_num} possible files.")

    print("\n\nThe following files are corrupted / not recognized:\n\n" + "\n".join(str(item) for item in sorted(corrupted_files)))
    print("\nDo you want me to delete them? [y/n]")
    choice = input()
    if choice == "n":
        return
    if choice != "y":
        print("I am going to interpret this as a no!")
        return

    for file in corrupted_files:
        file.unlink()



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
    request_helper = RequestHelper(user)
    pre_status.stop()

    restore_database_state(request_helper)
    delete_missing_files_from_database(request_helper)




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
