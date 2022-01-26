#!/usr/bin/env python3
import os
import subprocess
import sys
from configparser import ConfigParser
from getpass import getpass
from typing import List, Tuple, Optional, Union, Set, Any

from isisdl.backend.crypt import encryptor, get_credentials, store_user
from isisdl.backend.downloads import SessionWithKey
from isisdl.backend.utils import get_input, User, path, clear, config, get_default_config, acquire_file_lock
from isisdl.settings import is_first_time, is_windows, is_testing, database_file_location, config_clear_screen, is_autorun, master_password, timer_file_location, service_file_location

explanation_depth = "2"
indent = "    "


def generic_prompt(question: str, values: List[Tuple[str, Union[str, bool, None], str, str]], default: int, overwrite_output: Optional[str] = None,
                   allow_stored: Optional[Union[str, int]] = None) -> str:
    if overwrite_output:
        return overwrite_output

    if config_clear_screen:
        clear()

    names = []
    print(question + "\n")
    for i, (val, name, tldr, detail) in enumerate(values):
        names.append(name if name is not None else str(i))
        print(f"{indent}{i}. {val}{' [default]' if i == default else ''}")
        if explanation_depth > "0":
            if tldr:
                print()
                for item in tldr.split("\n"):
                    print(f"{indent * 2} {item}")

        if explanation_depth > "1":
            if detail:
                print()
                for item in detail.split("\n"):
                    print(f"{indent * 2} {item}")

        print("\n")

    allowed = {str(i) for i in range(len(values))} | {""}
    if allow_stored is not None:
        allowed |= {"s"}
        print(f"{indent[:-1]}[s] Use the stored value {allow_stored}")
        print()

    choice = get_input(allowed)
    if choice == "":
        choice = str(default)

    elif choice == "s" and allow_stored is not None:
        choice = str(allow_stored)

    return names[int(choice)]


def bool_prompt(prev: Optional[Union[str, bool, None]], default: Optional[bool]) -> Optional[bool]:
    # Will return None iff [s] is selected.
    allowed = {"0", "1"}
    if default is not None:
        allowed.add("")

    if prev is not None:
        print(f"\n    [s] Use the stored option ", end="")
        allowed.add("s")

        if isinstance(prev, bool):
            print(("No", "Yes")[prev], end=".\n\n")  # Idk if I like this syntax :D
        else:
            print(f"`{prev}`.", end="\n\n")

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
    choice = bool_prompt(config["password"] and User.sanitize_name(config["username"]), True)

    if choice is None:
        return

    if choice == "":
        choice = True

    if choice is False:
        config["username"] = None
        config["password"] = None
        config["password_encrypted"] = None
        return

    while True:
        print("Please provide your authentication for ISIS.")
        username = input("Username: ")
        password = getpass("Password: ")

        print("\nChecking if the password works ...")
        worked = SessionWithKey.from_scratch(User(username, password))
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

    store_user(User(username, password), additional_passphrase)


def filename_prompt() -> None:
    if is_windows:
        forbidden_chars = "<>:\"/\\|?*"
    else:
        forbidden_chars = "/"

    clear()
    print(f"""Some programs / programming languages have restrictions
or inconveniences when it comes to working with special characters.

To combat this you can enable a safe-mode for the file names.
If enabled, only ASCII letters + digits + "." are allowed as filenames.

In order to maintain readability of Filenames,
the next character after a whitespace is capitalized.

E.g. "I am a wîerd 💖 filename" → "IAmAWierdFilename"


Note:
The character{'s' if is_windows else ''} `{forbidden_chars}` {'are' if is_windows else 'is'} always replaced (not supported on a filesystem level).
When changing this option every file will be re-downloaded.


Do you want to enable file name replacing?

    [0] No  [default]
        
    [1] Yes
""")

    choice = bool_prompt(config["filename_replacing"], False)

    if choice is None:
        return

    config["filename_scheme"] = choice


def throttler_prompt() -> None:
    clear()
    print("""If you wish you can throttle your download speed to a limit.
Do you want to do so?

Note: You may overwrite this option by setting the `-d, --download-rate` flag.

    [0] No  [default]
    
    [1] Yes
""")

    choice = bool_prompt(config["throttle_rate"], False)

    if choice is None:
        return

    if choice == "":
        choice = False

    if choice is False:
        config["throttle_rate"] = None
        return

    while True:
        print()
        try:
            amount = str(int(input("How many MiB/s am I allowed to consume? ")))
            config["throttle_rate"] = amount
            return
        except ValueError as ex:
            print(f"\nI did not quite catch that:\n{ex}\n\n")


def timer_prompt() -> None:
    if is_windows:
        return

    def run_cmd_with_error(args: List[str]) -> None:
        result = subprocess.run(args, stderr=subprocess.PIPE, stdout=subprocess.PIPE)

        if result.returncode:
            print("\033[1;91mError!\033[0m")
            print(f"The command `{' '.join(result.args)}` exited with exit code {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}")
            print("\nPress [enter] to continue")
            input()

    clear()
    print("[Linux only]\n\nDo you want me to install a systemd timer to run `isisdl` every hour?\n")

    not_systemd = subprocess.check_call(["systemctl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    if not_systemd:
        print("""\033[1;91mError!\033[0m
It seams as if you are not running systemd.
Since this feature is systemd specific, I can't install it on your system.
If you think this is a bug please submit an error report at 
https://github.com/Emily3403/isisdl/issues

Press [enter] to continue.""")
        input()
        return

    print("If you enable this option the files will automagically appear in\n`isisdl_downloads` and you will never have to execute `isisdl` again.")

    if config["password_encrypted"]:
        print("""\n\033[1;91mError!\033[0m
I cannot run `isisdl` automatically if the password is encrypted.
Do you wish to store the password unencrypted?

    [0] No
    
    [1] Yes
""")
        choice = bool_prompt(None, None)

        if choice is False:
            return

        user = get_credentials()
        store_user(user)
        print("\nThe password is now stored unencrypted.\n")
        print("Do you wish to enable the timer?")

    print(f"""
Note:
The configuration file is located at 
`{timer_file_location}`
if you want to tune the time manually

    [0] No
    
    [1] Yes  [default]
""")

    allowed = {"0", "1", ""}
    if os.path.exists(timer_file_location):
        print("    2. No, but remove the timer\n")
        allowed.add("2")

    choice = get_input(allowed)

    if choice == "0":
        return

    if choice == "2":
        run_cmd_with_error(["systemctl", "--user", "disable", "--now", "isisdl.timer"])
        run_cmd_with_error(["systemctl", "--user", "daemon-reload"])

        if os.path.exists(timer_file_location):
            os.remove(timer_file_location)

        if os.path.exists(service_file_location):
            os.remove(service_file_location)

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
        f.write(f"""# isisdl autorun timer
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
    print("""In order to ensure that all courses are downloaded correctly I would like to
collect some metadata from your courses, setup and configuration of isisdl.

I've previously relied on assertions and users reporting these assertions on github.
This system is really inconvenient for both parties and wasts a lot of time.

If you allow it, the program `isisdl` will automatically contact a server when it can report something.

I collect the following:
- Wrong blacklisting of urls
- If files are missing upon rediscovery
- If two files have the same size (or for videos the same length)
- Your Platform
- Your configuration
""")
    choice = bool_prompt(config["telemetry_policy"], True)

    config["telemetry_policy"] = choice


def update_policy_prompt() -> None:
    prev_choice = config["update_policy"]

    print("""Do you want me to auto-install updates when available?

    [0] No
    
    [1] Install from github
        The version of Github is by design always more recent than the one on pip.
        It should have no stability issues since the update is only downloaded once it passes the tests.
    
    [2] Install from pip
        This build should be always working. Usually pushed a few days after github release.
    
    """)

    # TODO: Stored value



    config["update_policy"] = choice


# TODO: Default values
#   Cron and no store of passwords?


def main() -> None:
    # acquire_file_lock()
    if is_autorun:
        exit(127)

    print(f"""I will guide you through a short configuration phase of about 4min.
It is recommended that you read the options carefully.

You can
    [d] {'accept' if is_first_time else 'reset to'} the defaults
    [e] export the current configuration

If you want to {'accept' if is_first_time else 'reset to'} the default press [d] and [enter].
    """)
    # choice = input("")
    choice = ""
    if choice.lower() == "d":
        print(f"\n{'Accepted' if is_first_time else 'Reset to'} the defaults!")
        return


    timer_prompt()
    authentication_prompt()

    filename_prompt()

    throttler_prompt()
    update_policy_prompt()
    telemetry_data_prompt()

    print("Thank you for your time - everything is saved!")


if __name__ == "__main__":
    default_config = get_default_config()
    main()
