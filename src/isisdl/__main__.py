#!/usr/bin/env python3

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.bin import sync_database
from isisdl.backend.utils import logger, args, database_helper
from isisdl.version import __version__


def maybe_print_version_and_exit() -> None:
    if not args.version:
        return

    print(__version__)
    exit(0)


def main() -> None:
    maybe_print_version_and_exit()

    user = get_credentials()

    dl = CourseDownloader(user)

    dl.start()

    print("\nDone! Have a nice day ^.^")


# TODO:
#   Autolog to server
#       → delete logger

#   H265


if __name__ == '__main__':
    database_helper.get_state()
    main()
