#!/usr/bin/env python3
import os
from collections import defaultdict
from hashlib import sha256
from typing import Dict, List

from isisdl.backend.api import Course
from isisdl.backend.checksums import CheckSumHandler
from isisdl.share.settings import download_dir_location
from isisdl.share.utils import path, logger, CriticalError


def main():
    def print_percent(num: int, max_num: int):
        return f"{num} / {max_num} = {num / (max_num or 1) * 100}%"

    failed_one = False
    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)

        checksum_mapping = {}
        csh = CheckSumHandler(course, autoload_checksums=False)

        for file in course.list_files():
            with file.open("rb") as f:
                checksum = csh.calculate_checksum(f)
                if checksum is None:
                    continue

                checksum_mapping.update({file.as_posix(): checksum})

        checksums: Dict[str, int] = {}
        for key, value in checksum_mapping.items():
            checksums.setdefault(value, 0)
            checksums[value] += 1

        if len(checksum_mapping) == len(checksums):
            continue

        failed_one = True

        logger.info(f"Analyzing course {course}")
        logger.info(f"Number of files with the same checksum: {print_percent(sum(item for item in checksums.values() if item > 1), len(checksum_mapping))}")

        rev_checksums: Dict[str, List[str]] = {}
        for key, value in checksum_mapping.items():
            rev_checksums.setdefault(value, list()).append(key)

        same_checksums = {k: v for k, v in rev_checksums.items() if len(v) > 1 and any(os.path.basename(v[0]) != os.path.basename(item) for item in v)}

        def sha256sum(filename):
            sha = sha256()
            with open(filename, 'rb', buffering=0) as f:
                while True:
                    data = f.read(1024 * 64)
                    if not data:
                        break
                    sha.update(data)

            return sha.hexdigest()

        for key_, value_ in same_checksums.items():
            if len(value_) > 1:
                # Now test if the files are actually equal
                chs = {file: sha256sum(file) for file in value_}
                m_len = max(map(lambda x: len(os.path.basename(x)), chs))

                chs_rev = defaultdict(list)
                for key, value in chs.items():
                    chs_rev[value].append(key)

                logger.info(f"Number of files with different contents and same checksum: {print_percent(sum(len(item) if len(item) == 1 else 0 for item in chs_rev.values()), len(checksum_mapping))}")

                logger.debug(
                    f"The following have the checksum {key_}:\n\n" + f"{'Are equal' if all(item == sha256sum(value_[0]) for item in chs.values()) else 'Not equal'}\n\n" + "\n".join(value_) + "\n\n"
                    + "\n".join(f"{os.path.basename(file).ljust(m_len)}  {sha}" for file, sha in chs.items()) + "\n")

    if not failed_one:
        logger.info("I could not find any conflicts!")


if __name__ == '__main__':
    main()
