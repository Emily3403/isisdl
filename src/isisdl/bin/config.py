#!/usr/bin/env python3
import os
import subprocess
import sys
from getpass import getpass
from typing import List, Optional, Union, Set

import math
import yaml

from isisdl.backend.crypt import get_credentials, store_user
from isisdl.backend.downloads import SessionWithKey
from isisdl.backend.request_helper import RequestHelper
from isisdl.backend.utils import get_input, User, clear, config, error_text, generate_current_config_str, on_kill, run_cmd_with_error, acquire_file_lock_or_exit
from isisdl.settings import is_windows, is_autorun, timer_file_location, service_file_location, export_config_file_location, working_dir_location

was_in_configuration = False


def stored_prompt(prev: Optional[Union[bool, str, int, None]], allowed: Set[str]) -> None:
    if prev is None:
        return

    print("\n    [s] Use the stored option ", end="")
    allowed.add("s")

    if isinstance(prev, bool):
        print(("No", "Yes")[prev], end=".\n\n")  # Idk if I like this syntax :D
    else:
        print(f"`{prev}`.\n")


def bool_prompt(prev: Optional[Union[bool, str, int, None]], default: Optional[bool]) -> Optional[bool]:
    # Will return None iff [s] is selected.
    allowed = {"0", "1"}
    if default is not None:
        allowed.add("")

    stored_prompt(prev, allowed)

    choice = get_input(allowed)
    if choice == "":
        return default

    if choice == "s":
        return None

    return bool(int(choice))


def authentication_prompt() -> None:
    clear()
    print("""Do you wish to store your password?

    [0] No

    [1] Yes  [default]
""")

    # https://stackoverflow.com/a/47007761
    choice = bool_prompt(config.user("password") and User.sanitize_name(str(config.user("username"))), True)

    if choice is None:
        return

    if choice is False:
        config.username = None
        config.password = None
        config.password_encrypted = None
        return

    while True:
        print("Please provide your authentication for ISIS.")
        username = input("Username: ")
        password = getpass("Password: ")

        print("\nChecking if the password works ...")
        user = User(username, password)
        worked = SessionWithKey.from_scratch(user)
        if worked is not None:
            print("ISIS accepted the password.")
            break

        print("ISIS does not accept the username / password. Please try again!\n")

    print()
    while True:
        additional_passphrase = getpass("Enter passphrase (empty for no passphrase): ")
        second = getpass("Enter same passphrase again: ")
        if additional_passphrase == second:
            break
        else:
            print("The passphrases do not match. Try again.\n")

    store_user(user, additional_passphrase)
    return


def filename_prompt() -> None:
    if is_windows:
        forbidden_chars = "<>:\"/\\|?*"
    else:
        forbidden_chars = "/"

    clear()
    print(f"""Some programs / programming languages have restrictions or
inconveniences when it comes to working with special characters.

To combat this you can enable a safe-mode for the file names and paths.
If enabled, only ASCII letters + digits + "." are permitted as filenames.

In order to maintain the readability of filenames,
the next character after a whitespace is capitalized.

E.g.
"I am / a \\ wierd 🐧 [filename].png" → "IAmAWierdFilename.png"


--- Note ---
The character{'s' if is_windows else ''} `{forbidden_chars}` {'are' if is_windows else 'is'} always replaced (not supported on a filesystem level).

When changing this option every file will be re-downloaded.
------------


    [0] No  [default]

    [1] Yes
""")
    default = config.default("filename_replacing")
    assert isinstance(default, bool)
    choice = bool_prompt(config.user("filename_replacing"), default)

    if choice is None:
        return

    config.filename_replacing = choice


def throttler_prompt() -> None:
    clear()
    print("""Do you want to enable a limit for you download speed?


--- Note ---
You may overwrite this option by setting the `-d, --download-rate` flag.
------------


    [0] No  [default]

    [1] Only impose a limit for when `isisdl` automatically runs

    [2] Yes
""")
    allowed = {"0", "1", "2", ""}

    if config.user("throttle_rate") and config.user("throttle_rate_autorun"):
        print(f"\n    [s] Use the stored option {config.user('throttle_rate')} MiB/s (system-wide), {config.user('throttle_rate_autorun')} MiB/s (autorun).\n")
        allowed.add("s")

    elif config.user("throttle_rate"):
        print(f"\n    [s] Use the stored option {config.user('throttle_rate')} MiB/s (system-wide).\n")
        allowed.add("s")

    elif config.user("throttle_rate_autorun"):
        print(f"\n    [s] Use the stored option {config.user('throttle_rate_autorun')} MiB/s (autorun).\n")
        allowed.add("s")

    choice = get_input(allowed)

    if choice == "s":
        return

    if choice == "" or choice == "0":
        config.throttle_rate = -1
        config.throttle_rate_autorun = -1
        return

    if choice == "1":
        config_str = "throttle_rate_autorun"
    else:
        config_str = "throttle_rate"

    while True:
        print()
        try:
            amount = int(input("How many MiB/s am I allowed to consume? "))
            setattr(config, config_str, amount)
            return
        except ValueError as ex:
            print(f"\nI did not quite catch that:\n{ex}\n")


def timer_prompt() -> None:
    def remove_systemd_timer() -> None:
        if not os.path.exists(timer_file_location):
            return

        run_cmd_with_error(["systemctl", "--user", "disable", "--now", "isisdl.timer"])
        run_cmd_with_error(["systemctl", "--user", "daemon-reload"])

        if os.path.exists(timer_file_location):
            os.remove(timer_file_location)

        if os.path.exists(service_file_location):
            os.remove(service_file_location)

    clear()
    print("[Linux exclusive]\n\nDo you want me to install a systemd timer to run `isisdl` every hour?\n\n"
          f"If you enable this option the files will automagically appear in\n`{working_dir_location}`\nand you will never have to execute `isisdl` manually again.")

    if is_windows:
        print(f"\n\n{error_text}\nIt seems as if you are running windows.\nAutomatically running `isisdl` is currently not supported.\n"
              "You can expect it to be supported in future updates.\n\nPress enter to continue")
        input()
        return

    try:
        subprocess.check_call(["systemctl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        print(f"""{error_text}
I cannot find the `systemctl` executable. Probably you do not have systemd installed.
Since this feature is systemd specific, I can't install it on your system.
If you think this is a bug please submit an error report at
https://github.com/Emily3403/isisdl/issues

Press enter to continue.""")
        input()
        return

    print()

    if config.user("password_encrypted"):
        print(f"""\n{error_text}
I cannot run `isisdl` automatically if the password is encrypted.
Do you wish to store the password unencrypted?

    [0] No

    [1] Yes
""")
        choice = bool_prompt(None, None)

        if choice is False:
            remove_systemd_timer()
            return

        user = get_credentials()
        store_user(user)
        print("\nThe password is now stored unencrypted.\n\n")
        print("Do you wish to enable the timer?")

    print(f"""
--- Note ---
The configuration file for the timer is located at
`{timer_file_location}`
if you want to tune the time manually
------------


    [0] No

    [1] Yes  [default]
""")

    choice = bool_prompt(os.path.exists(timer_file_location) or None, True)

    if choice is None:
        return

    if choice is False:
        remove_systemd_timer()
        return

    import isisdl.bin.autorun
    with open(service_file_location, "w") as f:
        f.write(f"""# isisdl autorun service
# This file was autogenerated by the `isisdl-config` utility.

[Unit]
Description=isisdl
Wants=isisdl.timer

[Service]
Type=oneshot
ExecStart={sys.executable} {isisdl.bin.autorun.__file__}

[Install]
WantedBy=multi-user.target
""")

    with open(timer_file_location, "w") as f:
        f.write("""# isisdl autorun timer
# This file was autogenerated by the `isisdl-config` utility.

[Unit]
Description=isisdl
Wants=isisdl.service

[Timer]
Unit=isisdl.service
OnCalendar=hourly

[Install]
WantedBy=timers.target
""")

    run_cmd_with_error(["systemctl", "--user", "enable", "--now", "isisdl.timer"])
    run_cmd_with_error(["systemctl", "--user", "daemon-reload"])


def telemetry_data_prompt() -> None:
    clear()
    print("""In order to ensure that all courses and files are downloaded correctly I would like
to collect some metadata from your courses, setup and configuration of isisdl.

I've previously relied on assertions and users reporting these assertions on github.
This system is really inconvenient for both parties and wastes a lot of time.

If you allow it, the program `isisdl` will automatically contact a server when it can report something.

    [0] No

    [1] Yes  [default]
""")
    default = config.default("telemetry_policy")
    assert isinstance(default, bool)
    choice = bool_prompt(config.user("telemetry_policy"), default)

    if choice is None:
        return

    config.telemetry_policy = choice


def update_policy_prompt() -> None:
    clear()
    print("""Do you want me to auto-install updates when available?

The version on github is by design always more recent than the one on pip.
It should have no stability issues since the update is only installed if it passes the tests.

The version on pip should be always working and with no issues.
It is usually pushed a few days after the github release.


    [0] No

    [1] Install from pip  [default]

    [2] Install from github

    [3] Notify me when an update is available on pip

    [4] Notify me when an update is available on github
""")

    allowed = {"", "0", "1", "2", "3", "4"}

    stored_prompt(config.user("update_policy"), allowed)
    choice: Optional[str] = get_input(allowed)

    if choice == "s":
        return

    elif choice == "0":
        choice = None
    elif choice == "1" or choice == "":
        choice = "install_pip"
    elif choice == "2":
        choice = "install_github"
    elif choice == "3":
        choice = "notify_pip"
    else:
        choice = "notify_github"

    config.update_policy = choice


def _list_prompt(is_whitelist: bool) -> Union[List[int], bool]:
    clear()
    check_list = config.whitelist if is_whitelist else config.blacklist
    print(f"""Do you wish to {'whitelist' if is_whitelist else 'blacklist'} any of your courses?


--- Note ---
You may overwrite this option by setting the `{'-w, --whitelist' if is_whitelist else '-b, --blacklist'}` flag.
------------


    [0] No  [default]

    [1] Yes
""")

    allowed = {"", "0", "1"}
    if check_list is not None:
        print(f"\n    [s] Use the stored option {sorted(check_list)}")
        allowed.add("s")

    choice = get_input(allowed)
    if choice == "s":
        return True

    if choice == "0" or choice == "":
        return False

    if RequestHelper._instance is None:
        print("\n(Getting information about courses ...)\n")

    user = get_credentials()
    helper = RequestHelper(user)
    if not helper.courses:
        print("No courses available ...   (cricket sounds)")
        input()
        return True

    print("Please provide a comma-seperated list of the course-numbers.\nE.g. \"0, 2, 3\"\n")

    max_len = math.ceil(math.log(len(helper.courses), 10))
    for i, course in enumerate(helper.courses):
        print(f"    [{i}]{' ' * (max_len - len(str(i)))}   {course.name}")

    print()
    while True:
        user_input = input()
        try:
            lst = [int(item) for item in user_input.split(",")]
            if not all(0 <= item < len(helper.courses) for item in lst):
                raise ValueError("Your input was not constrained to the listed choices.")

            break

        except Exception as ex:
            print(f"\nI did not quite catch that:\n{ex}\n")

    return [helper.courses[i].course_id for i in lst]


def whitelist_prompt() -> None:
    lst = _list_prompt(True)
    if lst is True:
        return

    if lst is False:
        config.whitelist = None
        return

    assert isinstance(lst, list)

    config.whitelist = lst

    # Reevaluate courses
    user = get_credentials()
    RequestHelper(user).get_courses()


def blacklist_prompt() -> None:
    lst = _list_prompt(False)
    if lst is True:
        return

    if lst is False:
        config.blacklist = None
        return

    assert isinstance(lst, list)
    config.blacklist = lst

    # Reevaluate courses
    user = get_credentials()
    RequestHelper(user).get_courses()


def dont_download_videos_prompt() -> None:
    clear()
    print("""Do you want to download videos on this device?

This usually takes up a lot of space on your hard drive and may take
a long time to download if you have a slow internet connection.


    [0] No

    [1] Yes  [default]
    """)

    prev = config.user("download_videos")
    assert prev is None or isinstance(prev, bool)
    choice = bool_prompt(prev, True)

    if choice is None:
        return

    config.download_videos = choice


def isis_config_wizard() -> None:
    # TODO:
    #   Select courses to be downloaded
    #   Rename each course individually
    #   decide if sub-folders should be created inside a course folder.
    #   set if external linked files should be downloaded (files like youtube videos).
    #
    print("Not yet supported!")
    exit(1)


def run_config_wizard() -> None:
    global was_in_configuration
    was_in_configuration = True

    authentication_prompt()

    whitelist_prompt()
    blacklist_prompt()
    dont_download_videos_prompt()
    filename_prompt()

    timer_prompt()
    throttler_prompt()
    update_policy_prompt()
    telemetry_data_prompt()
    was_in_configuration = False

    print("Thank you for your time - everything is saved!\n")


@on_kill(3)
def unexpected_exit_in_wizard() -> None:
    if was_in_configuration:
        print("\nThe configuration wizard was killed unexpectedly.\nI will continue with the default for all options which you have not configured.")


def main() -> None:
    acquire_file_lock_or_exit()
    if is_autorun:
        exit(1)

    print("""Hello there 👋

You can choose one of the following actions

    [ ] run the configuration wizard

    [v] view the current configuration
""")
    if not is_windows:
        print(f"    [e] export the current configuration to\n        `{export_config_file_location}`")

    choice = input()
    print()

    # if choice.lower() == "i":
    #     isis_config_wizard()
    #     return

    if choice.lower() == "v":
        print("\nThe configuration is the following:\n")
        print(yaml.dump(config.to_dict()))
        return

    if not is_windows and choice.lower() == "e":
        print("Exporting current configuration ...")
        with open(export_config_file_location, "w") as f:
            f.write(generate_current_config_str())
        return

    run_config_wizard()


if __name__ == "__main__":
    main()
