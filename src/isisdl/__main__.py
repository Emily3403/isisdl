#!/usr/bin/env python3


from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.bin import build_checksums
from isisdl.share.utils import logger, args
from isisdl.version import __version__


def maybe_print_version_and_exit():
    if not args.version:
        return

    print(__version__)
    exit(0)


def main():
    maybe_print_version_and_exit()
    build_checksums.main()

    user = get_credentials()

    dl = CourseDownloader(user)

    dl.start()

    logger.info("Done! Have a nice day ^.^")


# TODO:
#
#   isisdl-clean-names
#
#   init function
#
#   Autolog to server

# Maybe TODO:
#
#   Better settings / config


if __name__ == '__main__':
    main()
