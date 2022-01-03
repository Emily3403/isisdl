#!/usr/bin/env python3
import os
import time
from pathlib import Path
from typing import List, Tuple

from isisdl.share.settings import download_dir_location
from isisdl.share.utils import path, logger, calculate_checksum, database_helper


def main() -> None:
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

    missed_file_names: List[Tuple[str, str]] = [(database_helper.get_name_by_checksum(item), course) for item, course in missed_files]

    if missed_file_names:
        max_file_len = max(len(item[0]) for item in missed_file_names)

        logger.warning("Noticied missing files:\n" + "\n".join(f"{item.ljust(max_file_len)} → {course}" for item, course in missed_file_names))
        logger.warning("I am updating the database accordingly.")

    for item, _ in missed_files:
        database_helper.delete_by_checksum(item)

    logger.info(f"Successfully built all checksums in {time.perf_counter() - s:.3f}s.")


if __name__ == '__main__':
    main()
