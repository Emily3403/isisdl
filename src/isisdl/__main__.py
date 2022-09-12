#!/usr/bin/env python3
import sys

import isisdl.compress as compress
from isisdl.backend import sync_database
from isisdl.backend.config import init_wizard, config_wizard
from isisdl.backend.request_helper import CourseDownloader
from isisdl.settings import is_first_time, is_static, forbidden_chars, has_ffmpeg, fstype, is_windows, working_dir_location, python_executable, is_macos, is_online
from isisdl.utils import args, acquire_file_lock_or_exit, generate_error_message, install_latest_version, export_config, database_helper, config, migrate_database, Config, compare_download_diff
from isisdl.version import __version__


def print_version() -> None:
    print(f"""isisdl version {__version__}

Running on {"MacOS" if is_macos else "Windows" if is_windows else "Linux"}
This is{"" if is_static else " not"} the compiled version

working directory: {working_dir_location}
python executable: {python_executable}

database_version = {Config.default("database_version")}
{has_ffmpeg = }
{forbidden_chars = }
{fstype = }
""")


def _main() -> None:
    if is_first_time:
        print("""
It seems as if this is your first time executing isisdl. Welcome 💖

I will guide you through a short configuration phase of about 5min.
It is recommended that you read these options carefully.

You may simply press the Enter key to accept the default.

If you wish to re-configure me, run `isisdl --init` or `isisdl --config`.


Please press enter to continue.
""")
        input()
        init_wizard()
        config_wizard()
        sync_database.main()

    elif database_helper.get_database_version() < config.default("database_version"):
        if migrate_database() is False:
            sys.exit(1)

        sys.exit(0)

    elif args.version:
        print_version()
        sys.exit(0)

    acquire_file_lock_or_exit()

    if args.init:
        init_wizard()
        sys.exit(0)

    elif args.config:
        config_wizard()
        sys.exit(0)

    elif not is_windows and args.export_config:
        print("Exporting current configuration ...")
        export_config()
        sys.exit(0)

    elif args.delete_bad_urls:
        print("Deleting bad urls ...")
        database_helper.delete_bad_urls()
        sys.exit(0)

    if not is_online:
        print("I cannot establish an internet connection.")
        sys.exit(1)

    install_latest_version()

    if args.update:
        print("No new update available ... (cricket sounds)")
        sys.exit(0)

    elif args.sync:
        sync_database.main()
        sys.exit(0)

    elif args.compress:
        compress.main()
        sys.exit(0)

    elif args.download_diff:
        compare_download_diff()
        sys.exit(0)

    # elif args.subscribe:
    #    print("Due to legal reasons, this is currently not supported. :(")
    #    sys.exit(0)

    #         print("""Attention:
    # This option will lead to you subscribing to *every* publicly available ISIS course.
    #
    # Subscribing will be quite fast 10-20s, but unsubscribing takes a fe-minutes.
    # This behaviour is due to the fact that the API to unsubscribe from courses
    # is not yet implemented. (https://tracker.moodle.org/browse/MDL-64255)
    #
    # Please press enter to continue.
    # """)
    #
    #         input()
    #         subscribe_to_all_courses()
    #         sys.exit(0)

    # elif args.unsubscribe:
    #     print("Due to legal reasons, this is currently not supported. :(")
    #     sys.exit(0)

    # unsubscribe_from_courses()
    # sys.exit(0)

    else:
        # Main routine
        CourseDownloader().start()
        print("\nDone! Have a nice day ^.^")


def main() -> None:
    try:
        _main()
    except Exception as ex:
        generate_error_message(ex)


#   Change Database → Version 1.4
#       Make the size attribute not mandatory for a file
#           → Logger looses the ability to report total number of bytes available
#           → MediaContainer can't be compared with __gt__ → TODO: what does this cause? → Tests start failing in chop_down_size
#           → Loose the ability to _always_ check if a file exists → if a file does not have a size, it is not downloaded
#           → checking for conflict will be _way_ harder → TODO: How to solve? Videos at least have a video length size → Maybe use that?
#           → DownloadStatus won't have an ETA
#           → Syncing the Database will be of lower quality: Ignore all Documents and only restore the videos: Their name / url is the SHA-Sum of their content.
#
#       is_corrupted attribute change
#           → Note the last time checked and retry the url based on an exponential backoff strategy
#
#       Remove the path attribute
#           → Make the path of a file entirely dynamic and dependant on the configured state.
#             This should lead to a seamless migration of the directory when changing it's name.
#             This also enables easy renaming of courses and deselecting of the subdir option, assuming the directories have been moved accordingly.
#
#       No more json strings
#           → Extra table for user configuration
#
#       Make storing your password more secure
#           → Achieved by generating a random master password + random salt and store it in the database.
#             This enables for greater security since 1 table is all that is needed in order to crack multiple passwords
#
#       Verify the database state on every startup by iterating over all files + sizes and raising an error if the size and checksum don't match
#
#       These changes imply the following
#           → Don't check any URL's that are not extern
#           →

# TODO:
#
#   Check how many urls requested multiple times
#
#   Calculate the number of threads to use dynamically
#
#   Check what isisdl is doing after building request cache → why is it so slow in valgrind?
#
#   Argcomplete
#       https://pypi.org/project/argcomplete/
#       qmk can also do this
#   → Seems kinda hard / shitty to use
#
#   Compare program to check diffs against isia-tub
#       → More content
#
#   Throttling does not work when imposed via config ??
#
#   When exiting show exact done in.
#
#   When no new discovered files then don't show None but instead don't print anything at all.
#
#   Better course targeting mechanism by first downloading those where you have participated
#
#   Fix bug when first starting then it looks like stream


# Maybe TODO
#
#   fixing / bug hunting the compress
#
#   Have a variable for posix and linux
#
#   Static builds from github runners
#
#   Wiki tutorial for streaming


if __name__ == "__main__":
    main()
