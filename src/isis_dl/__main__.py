#!/usr/bin/env python3
import logging
import os
import atexit
from pathlib import Path
from typing import Dict, List

import requests

from isis_dl.backend.api import CourseDownloader, Course
from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.backend.crypt import get_credentials
from isis_dl.share.utils import create_logger, args, path, MediaType
import isis_dl.share.settings as settings


def startup():
    create_logger()

    def make(p):
        os.makedirs(path(p), exist_ok=True)

    make(settings.download_dir)
    make(settings.temp_dir)
    make(settings.intern_dir)
    make(settings.password_dir)


def find_files(course):
    paths = [Path(path(settings.download_dir, course, item)) for item in MediaType.list_dirs()]

    for directory in map(lambda x: x.iterdir(), paths):
        for file in directory:
            if file.name.startswith("."):
                continue

            if file.is_dir():
                # This is an archive. It cannot be restored.
                continue

            yield file


def _maybe_build_checksums_and_exit():
    for course in os.listdir(path(settings.download_dir)):
        the_course = Course(requests.Session(), course, "")

        csh = CheckSumHandler(the_course, autoload_checksums=False)

        for file in find_files(course):
            with file.open("rb") as f:
                checksum, _ = csh.maybe_get_chunk(f, f.name)

        csh.dump()


def maybe_build_checksums_and_exit():
    if not args.build_checksums:
        return

    _maybe_build_checksums_and_exit()

    exit(0)


def maybe_test_checksums_and_exit():
    if not args.test_checksums:
        return

    # Keep the checksums up to date.
    _maybe_build_checksums_and_exit()

    lf = "\n"

    def print_percent(num: int, max_num: int):
        return f"{num} / {max_num} = {num / (max_num or 1) * 100}%"

    for course in os.listdir(path(settings.download_dir)):
        logging.info(f"Analyzing course {course}")
        the_course = Course(requests.Session(), course, "")

        checksum_mapping = {}
        csh = CheckSumHandler(the_course, autoload_checksums=False)

        for file in find_files(course):
            with file.open("rb") as f:
                checksum, _ = csh.calculate_checksum(f, f.name)
                checksum_mapping.update({file.as_posix(): checksum})

        checksums = {item for item in checksum_mapping.values()}

        logging.info(f"Number of files with the same checksum: {print_percent(len(checksum_mapping) - len(checksums), len(checksum_mapping))}")
        if len(checksum_mapping) == len(checksums):
            continue

        rev_checksums: Dict[str, List[str]] = {}
        for key, value in checksum_mapping.items():
            rev_checksums.setdefault(value, list()).append(key)

        same_checksums = {k: v for k, v in rev_checksums.items() if len(v) > 1 and any(os.path.basename(v[0]) != os.path.basename(item) for item in v)}
        logging.info(f"Number of files with different filenames and same checksum: {print_percent(sum(len(item) for item in same_checksums.values()), len(checksum_mapping))}")

        for key, value in same_checksums.items():  # type: ignore
            if len(value) > 1:
                logging.debug(f"The following have the checksum {key}:\n{lf.join(value)}\n")

    # TODO

    exit(0)


def main():
    startup()

    maybe_build_checksums_and_exit()
    maybe_test_checksums_and_exit()

    user = get_credentials()

    dl = CourseDownloader.from_user(user)

    @atexit.register
    def goodbye():
        logging.info("Storing checksums…")
        dl.finish()
        logging.info("Done! Bye Bye ^.^")

    dl.start()


if __name__ == '__main__':
    main()
