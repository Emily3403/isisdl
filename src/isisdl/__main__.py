#!/usr/bin/env python3

import isisdl.bin.build_checksums as build_checksums
import isisdl.bin.unpack_archives as unpack_archives
from isisdl.backend.request_helper import CourseDownloader
from isisdl.backend.crypt import get_credentials
from isisdl.backend.downloads import throttler, Status
from isisdl.share.settings import download_chunk_size
from isisdl.share.utils import on_kill, logger, HumanBytes, args


def maybe_print_version_and_exit():
    if not args.version:
        return

    print("isisdl Version 0.4")  # TODO
    exit(0)


def main():
    maybe_print_version_and_exit()

    build_checksums.main()

    user = get_credentials()

    dl = CourseDownloader(user)

    @on_kill(2)
    def goodbye():
        Status._running = False
        logger.info("Storing checksums…")
        dl.finish()
        usage, unit = HumanBytes.format(throttler.times_get * download_chunk_size)
        logger.info(f"Downloaded {usage:.2f} {unit} of Data.")

        logger.debug("Timings:\n" + "\n".join(f"{(key + ':').ljust(9)} {value if value is not None else 0:.3f}s" for key, value in CourseDownloader.timings.items()))

        logger.info("Unzipping archives…")
        unpack_archives.main()
        logger.info("Done! Have a nice day ^.^")

    dl.start()
    dl.finish()


# TODO:
#
#   Better list of file downloads?
#
#   Credentials multiple errors
#
#   Try checksums
#       → If checksum != log an error
#
#   Exponential time decay
#
#   Umlaute
#
#   Only save a login token
#
#   When downloading use queue to move urls around → build + checksum can be merged
#
#   Expected download size not working


# Maybe todo

#   Check for corrupted files
#
#   Notify via telegram


if __name__ == '__main__':
    main()
