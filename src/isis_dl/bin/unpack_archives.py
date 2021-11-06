#!/usr/bin/env python3

import os
import shutil
import time

from isis_dl.backend.api import Course
from isis_dl.share.settings import download_dir_location, unpacked_archive_dir_location
from isis_dl.share.utils import path, logger


def main():
    s = time.time()
    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)

        for file in course.list_files():
            try:
                new_path = course.path(unpacked_archive_dir_location, os.path.splitext(file.name)[0])
                shutil.unpack_archive(file.as_posix(), new_path)

            except shutil.ReadError:
                pass

    logger.info(f"Successfully unpacked all checksums in {time.time() - s:.3f}s.")


if __name__ == '__main__':
    main()
