"""
This file provides binary-like functions and will exit if any of those are triggered.
"""
import os
import shutil
from typing import Dict, List

from isis_dl.backend.api import Course
from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.share.settings import download_dir_location, unpacked_archive_dir_location, unpacked_archive_suffix
from isis_dl.share.utils import path, args, logger


def _maybe_build_checksums_and_exit():
    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)

        csh = CheckSumHandler(course, autoload_checksums=False)

        for file in course.list_files():
            with file.open("rb") as f:
                checksum, _ = csh.calculate_checksum(f, f.name)
                csh.add(checksum)

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

    def print_percent(num: int, max_num: int):
        return f"{num} / {max_num} = {num / (max_num or 1) * 100}%"

    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)
        logger.info(f"Analyzing course {course}")

        checksum_mapping = {}
        csh = CheckSumHandler(course, autoload_checksums=False)

        for file in course.list_files():
            with file.open("rb") as f:
                checksum, _ = csh.calculate_checksum(f, f.name)
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

        for key, value in same_checksums.items():  # type: ignore
            if len(value) > 1:
                same = "\n".join(value)
                logger.debug(f"The following have the checksum {key}:\n{same}\n")

    exit(0)


def maybe_unpack_archive_and_exit():
    if not args.unzip:
        return

    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)

        for file in course.list_files():
            try:
                new_path = course.path(unpacked_archive_dir_location, file.name + unpacked_archive_suffix)
                # os.makedirs(new_path, exist_ok=True)
                shutil.unpack_archive(file.as_posix(), new_path)

            except shutil.ReadError:
                pass

        # unpack = args.unzip and self.media_type == MediaType.archive
        # if unpack:
        #     _fn = os.path.splitext(filename)[0]
        #     filename = path(temp_dir, self.name)

        # if unpack:
        #     try:
        #         shutil.unpack_archive(filename, _fn)
        #     except (EOFError, zipfile.BadZipFile, shutil.ReadError):
        #         logger.warning(f"Bad zip file: {self.name}")
        #         x = zipfile.ZipFile(filename)
        #         x.extractall(path=_fn)
        #         print()

    exit(0)


def call_all():
    maybe_build_checksums_and_exit()
    maybe_test_checksums_and_exit()
    maybe_unpack_archive_and_exit()
