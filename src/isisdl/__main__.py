#!/usr/bin/env python3
from http.client import HTTPSConnection

from isisdl.backend.crypt import get_credentials
from isisdl.backend.request_helper import CourseDownloader
from isisdl.backend.update import install_latest_version
from isisdl.backend.utils import args, acquire_file_lock_or_exit, generate_error_message
from isisdl.bin.config import run_config_wizard
from isisdl.settings import is_first_time
from isisdl.version import __version__
import isisdl.bin.sync_database as sync_database


def maybe_print_version_and_exit() -> None:
    if not args.version:
        return

    print(f"isisdl Version {__version__}")
    exit(0)


def check_online() -> None:
    # Copied from https://stackoverflow.com/a/29854274
    conn = HTTPSConnection("8.8.8.8", timeout=5)
    try:
        conn.request("HEAD", "/")
        return
    except Exception:
        print("I cannot establish an internet connection.")
        exit(1)
    finally:
        conn.close()


def _main() -> None:
    maybe_print_version_and_exit()
    acquire_file_lock_or_exit()
    check_online()
    install_latest_version()

    # is_first_time = True
    if is_first_time:
        print("""It seems as if this is your first time executing isisdl. Welcome 💖

I will guide you through a short configuration phase of about 5min.
It is recommended that you read the options carefully.
If you wish to re-configure me run `isisdl-config`.

If you think this is a mistake, click yourself through the wizard
and I will rediscover your files afterwards.

Please press enter to continue.""")
        input()
        run_config_wizard()
        sync_database._main()

    dl = CourseDownloader(get_credentials())

    dl.start()

    print("\n\nDone! Have a nice day ^.^")


def main() -> None:
    try:
        _main()
    except Exception:
        generate_error_message()


# TODO:
#   Autolog to server
#   Use mp4 metadata to recognize files

if __name__ == "__main__":
    main()
