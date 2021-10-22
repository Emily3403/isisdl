#!/usr/bin/env python3
import logging
import os
import atexit
from pathlib import Path
from typing import Dict, List

import requests
from bs4 import GuessedAtParserWarning

from isis_dl.backend.api import CourseDownloader, Course
from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.backend.crypt import get_credentials
from isis_dl.share.utils import create_logger, args, path, MediaType
import isis_dl.share.settings as settings

import warnings

warnings.filterwarnings('ignore', category=GuessedAtParserWarning)


def startup():
    def prepare_dir(p):
        os.makedirs(path(p), exist_ok=True)

    def prepare_file(p):
        if not os.path.exists(path(p)):
            with open(path(p), "w"):
                pass

    def create_link_to_settings_file(file: str):
        fp = path(settings.settings_file_location)

        def restore_link():
            os.symlink(file, fp)

        if os.path.exists(fp):
            if os.path.realpath(fp) != file:
                os.remove(fp)
                restore_link()
        else:
            restore_link()

    #
    create_logger()

    prepare_dir(settings.download_dir)
    prepare_dir(settings.temp_dir)
    prepare_dir(settings.intern_dir)
    prepare_dir(settings.password_dir)

    create_link_to_settings_file(os.path.abspath(settings.__file__))
    prepare_file(settings.whitelist_file_name)
    prepare_file(settings.blacklist_file_name)


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

        checksums: Dict[str, int] = {}
        for key, value in checksum_mapping.items():
            checksums.setdefault(value, 0)
            checksums[value] += 1

        # checksums = {item for item in checksum_mapping.values()}

        logging.info(f"Number of files with the same checksum: {print_percent(sum(item for item in checksums.values() if item > 1), len(checksum_mapping))}")
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


def maybe_unpack_archive_and_exit():
    # unpack = args.unzip and self.media_type == MediaType.archive
    # if unpack:
    #     _fn = os.path.splitext(filename)[0]
    #     filename = path(temp_dir, self.name)

    # if unpack:
    #     try:
    #         shutil.unpack_archive(filename, _fn)
    #     except (EOFError, zipfile.BadZipFile, shutil.ReadError):
    #         logging.warning(f"Bad zip file: {self.name}")
    #         x = zipfile.ZipFile(filename)
    #         x.extractall(path=_fn)
    #         print()

    pass


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


# TODO:

#   TL;DR of how password storing works
#
#   Only unzip when prompted
#
#   Better checksum → include file size + other metadata?
#
#   More warnings
#
#   run.sh → -n 8 -s 0.2 -l debug etc.


# Maybe todo

#   Add rate limiter


if __name__ == '__main__':
    main()
