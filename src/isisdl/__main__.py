#!/usr/bin/env python3


from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import Status
from isisdl.backend.request_helper import CourseDownloader
from isisdl.bin import build_checksums
from isisdl.share.utils import logger, args


def maybe_print_version_and_exit():
    if not args.version:
        return

    print("isisdl Version 0.5.1")  # TODO
    exit(0)


def main():
    maybe_print_version_and_exit()
    build_checksums.main()

    user = get_credentials()

    dl = CourseDownloader(user)

    dl.start()

    Status.running = False
    logger.info("Done! Have a nice day ^.^")


# TODO:
#
#   Better list of file downloads?
#
#   When downloading use queue to move urls around → build + checksum can be merged
#
#   Expected download size not working
#
#   Flag for no videos
#
#   Attach the header to the MediaContainer
#
#   Version
#
#
#   isisdl-clean-names
#
#   init function
#
#   Autolog to server

# Maybe todo

#   Try checksums
#       → If checksum != log an error
#
#   Check for corrupted files
#
#   Notify via telegram
#
#   Better settings / config
#


if __name__ == '__main__':
    main()
