#!/usr/bin/env python3
import json
import os
import shutil
import time

from isisdl.backend.api import Course
from isisdl.share.settings import download_dir_location, unpacked_archive_dir_location
from isisdl.share.utils import path, logger


def main():
    s = time.time()
    for _course in os.listdir(path(download_dir_location)):
        try:
            course = Course.from_name(_course)
        except (FileNotFoundError, KeyError, json.decoder.JSONDecodeError):
            logger.error(f"I could not find the ID for course {_course}.")
            continue

        for file in course.list_files():
            try:
                new_path = course.path(unpacked_archive_dir_location, os.path.splitext(file.name)[0])
                shutil.unpack_archive(file.as_posix(), new_path)

            except shutil.ReadError:
                pass

    logger.info(f"Successfully unpacked all checksums in {time.time() - s:.3f}s.")


if __name__ == '__main__':
    main()
