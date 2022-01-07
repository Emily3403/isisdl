#!/usr/bin/env python3

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.backend.utils import args, database_helper
from isisdl.settings import is_first_time
from isisdl.version import __version__
import isisdl.bin.config as config


def maybe_print_version_and_exit() -> None:
    if not args.version:
        return

    print(__version__)
    exit(0)


def main() -> None:
    maybe_print_version_and_exit()

    if is_first_time:
        print("It seams as if this is your first time executing isisdl. Welcome <3\n")
        config.main()

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
