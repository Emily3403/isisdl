#!/usr/bin/env python3
import os
import time

from isis_dl.backend.api import Course
from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.share.settings import download_dir_location
from isis_dl.share.utils import path, logger, CriticalError


def main():
    s = time.time()
    for _course in os.listdir(path(download_dir_location)):
        course = Course.from_name(_course)

        csh = CheckSumHandler(course, autoload_checksums=True)

        for file in course.list_files():
            with file.open("rb") as f:
                checksum = csh.calculate_checksum(f)
                if checksum is None:
                    # This is just a dummy placeholder. Mypy doesn't (and can't) know that checksum will never be None.
                    raise CriticalError

                csh.add(checksum)

        csh.dump()

    logger.info(f"Successfully built all checksums in {time.time() - s:.3f}s.")


if __name__ == '__main__':
    main()
