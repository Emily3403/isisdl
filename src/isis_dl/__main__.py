#!/usr/bin/env python3
import collections
import logging
import os
import atexit
import shutil
from pathlib import Path
from typing import Dict, Set

import requests

from isis_dl.backend.api import CourseDownloader, Course
from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.backend.crypt import get_credentials
from isis_dl.share.utils import create_logger, get_args, args, path, MediaType
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
    for file in Path(path(settings.download_dir, course)).rglob("*.*"):
        if file.name.startswith("."):
            continue

        if file.is_dir():
            # This is an archive: pack in the temp dir.
            name, ext = os.path.splitext(file.as_posix())
            new_file_name = path(settings.temp_dir, os.path.basename(name))

            shutil.make_archive(new_file_name, ext.replace(".", ""), file)
            file = Path(new_file_name + ext)

        yield file


def _maybe_build_checksums_and_exit():
    for course in os.listdir(path(settings.download_dir)):
        the_course = Course.from_path(requests.Session(), course)
        if the_course is None:
            continue

        csh = CheckSumHandler(the_course, autoload_checksums=False)

        files = []
        for categories in MediaType.list_dirs():
            for (dirpath, dirnames, filenames) in os.walk(path(settings.download_dir, course, categories)):
                if filenames:
                    files.extend([(os.path.splitext(file), os.path.join(dirpath, file)) for file in filenames])
                    print()

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

    _maybe_build_checksums_and_exit()

    lf = "\n"

    for course in os.listdir(path(settings.download_dir)):
        the_course = Course.from_path(requests.Session(), course)
        if the_course is None:
            continue

        checksum_mapping = {}
        csh = CheckSumHandler(the_course, autoload_checksums=False)

        for file in find_files(course):
            with file.open("rb") as f:
                checksum, _ = csh._calculate_checksum(f, f.name)
                checksum_mapping.update({file.as_posix(): checksum})

        checksums = {item for item in checksum_mapping.values()}

        num_dup = len(checksum_mapping) - len(checksums)
        logging.info(f"Number of duplicate files for course {course}: {num_dup} = {num_dup / len(checksum_mapping) * 100}%")
        if len(checksum_mapping) == len(checksums):
            continue

        rev_checksums: Dict[str, Set[str]] = {}
        for key, value in checksum_mapping.items():
            rev_checksums.setdefault(value, set()).add(key)

        for key, value in rev_checksums.items():  # type: ignorea
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
