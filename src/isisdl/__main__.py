#!/usr/bin/env python3
from typing import NoReturn

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.bin import build_checksums
from isisdl.share.utils import logger, args
from isisdl.version import __version__


def maybe_print_version_and_exit() -> None:
    if not args.version:
        return

    print(__version__)
    exit(0)


def main() -> None:
    maybe_print_version_and_exit()
    build_checksums.database_subset_files()

    user = get_credentials()

    dl = CourseDownloader(user)

    dl.start()

    logger.info("Done! Have a nice day ^.^")


# TODO:
#   isisdl-clean-names
#   Autolog to server
#   Auto detect files
#   Status fix whitespace
#   Only 1 session

#   Have some prompts upon first activation of function


if __name__ == '__main__':
    main()
