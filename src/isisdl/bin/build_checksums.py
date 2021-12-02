#!/usr/bin/env python3
import json
import os
import time

from isisdl.backend.api import Course
from isisdl.backend.checksums import CheckSumHandler
from isisdl.share.settings import download_dir_location
from isisdl.share.utils import path, logger


def main():
    s = time.time()
    for _course in os.listdir(path(download_dir_location)):
        try:
            course = Course.from_name(_course)
        except (FileNotFoundError, KeyError, json.decoder.JSONDecodeError):
            logger.error(f"I could not find the ID for course {_course}.")
            continue

        csh = CheckSumHandler(course, autoload_checksums=True)

        for file in course.list_files():
            try:
                with file.open("rb") as f:
                    checksum = csh.calculate_checksum(f)
                    if checksum is None:
                        continue

                    csh.add(checksum)
            except OSError:
                logger.warning(f"I could not open the file {file}. Ignoring this file.")

        csh.dump()

    logger.info(f"Successfully built all checksums in {time.time() - s:.3f}s.")


if __name__ == '__main__':
    main()
