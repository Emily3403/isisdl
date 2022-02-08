#!/usr/bin/env python3

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader, RequestHelper
from isisdl.backend.update import install_latest_version
from isisdl.backend.utils import args, acquire_file_lock_or_exit, generate_error_message
from isisdl.bin.config import run_config_wizard
from isisdl.settings import is_first_time
from isisdl.version import __version__


def maybe_print_version_and_exit() -> None:
    if not args.version:
        return

    print(__version__)
    exit(0)


def _main() -> None:
    maybe_print_version_and_exit()
    acquire_file_lock_or_exit()
    install_latest_version()

    # is_first_time = True
    if is_first_time:
        print("""It seams as if this is your first time executing isisdl. Welcome 💖

I will guide you through a short configuration phase of about 5min.
It is recommended that you read the options carefully.
If you wish to re-configure me run `isisdl-config`.

Please press enter to continue.""")
        input()
        run_config_wizard()

    dl = CourseDownloader(get_credentials())

    dl.start()

    print("\nDone! Have a nice day ^.^")


def main() -> None:
    try:
        _main()
    except Exception:
        generate_error_message()


# TODO:
#   Autolog to server
#   H265
#   async
#
#


if __name__ == "__main__":
    main()
