#!/usr/bin/env python3

import isis_dl.bin.build_checksums as build_checksums
import isis_dl.bin.unpack_archives as unpack_archives
from isis_dl.backend.api import CourseDownloader
from isis_dl.backend.crypt import get_credentials
from isis_dl.backend.downloads import throttler, Status
from isis_dl.share.settings import download_chunk_size
from isis_dl.share.utils import on_kill, logger, HumanBytes, args


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

        logger.debug("Timings:\n" + "\n".join(f"{(key + ':').ljust(9)} {value:.3f}s" for key, value in CourseDownloader.timings.items()))
        logger.debug(f"Had error: {CourseDownloader.had_error}")

        logger.info("Unzipping archives…")
        unpack_archives.main()
        logger.info("Done! Bye Bye ^.^")

    dl.start()
    dl.finish()


# TODO:
#
#   Try to reproduce 503
#
#   Better list of file downloads?
#
#   Automatic upload to PyPi: https://www.caktusgroup.com/blog/2021/02/11/automating-pypi-releases/
#
#   Github actions → environment variables
#
#   Credentials multiple errors
#
#   Zipped archives → double
#
#   Fake user agent

# Maybe todo

#   Change instantiation of MediaContainer into web-requests + multiprocessing. Should be more efficient - but is fast enough already
#
#   When calculating a hash the server does not always respect the Range parameter.
#       → Store the 512 Byte hash as an identifier and associate the hash algorithm based on that.
#       → Meh…
#
#   Check for corrupted files


if __name__ == '__main__':
    main()
