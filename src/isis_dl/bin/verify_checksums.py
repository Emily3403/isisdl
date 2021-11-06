#!/usr/bin/env python3

import os
from typing import Dict, List

import isis_dl.bin.build_checksums as build_checksums
from isis_dl.backend.api import Course
from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.share.settings import download_dir_location
from isis_dl.share.utils import path, logger, CriticalError


def main():
    # Re-build the checksums
    build_checksums.main()

    def print_percent(num: int, max_num: int):
        return f"{num} / {max_num} = {num / (max_num or 1) * 100}%"

    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)
        logger.info("")
        logger.info(f"Analyzing course {course}")

        checksum_mapping = {}
        csh = CheckSumHandler(course, autoload_checksums=False)

        for file in course.list_files():
            with file.open("rb") as f:
                checksum = csh.calculate_checksum(f)
                if checksum is None:
                    # This is just a dummy placeholder. Mypy doesn't (and can't) know that checksum will never be None.
                    raise CriticalError

                checksum_mapping.update({file.as_posix(): checksum})

        checksums: Dict[str, int] = {}
        for key, value in checksum_mapping.items():
            checksums.setdefault(value, 0)
            checksums[value] += 1

        logger.info(f"Number of files with the same checksum: {print_percent(sum(item for item in checksums.values() if item > 1), len(checksum_mapping))}")
        if len(checksum_mapping) == len(checksums):
            continue

        rev_checksums: Dict[str, List[str]] = {}
        for key, value in checksum_mapping.items():
            rev_checksums.setdefault(value, list()).append(key)

        same_checksums = {k: v for k, v in rev_checksums.items() if len(v) > 1 and any(os.path.basename(v[0]) != os.path.basename(item) for item in v)}
        logger.info(f"Number of files with different filenames and same checksum: {print_percent(sum(len(item) for item in same_checksums.values()), len(checksum_mapping))}")

        for key_, value_ in same_checksums.items():
            if len(value_) > 1:
                same = "\n".join(value_)
                logger.debug(f"The following have the checksum {key_}:\n{same}\n")


if __name__ == '__main__':
    main()
