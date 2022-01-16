#!/usr/bin/env python3
import sys
from getpass import getpass
from typing import List, Tuple, Optional, Union

from isisdl.backend.crypt import encryptor
from isisdl.backend.utils import config_helper, get_input, User, path, clear
from isisdl.settings import is_first_time, is_windows, is_testing, database_file_location, config_clear_screen

explanation_depth = "2"
indent = "    "


def generic_prompt(question: str, values: List[Tuple[str, str, str]], default: int, overwrite_output: Optional[str] = None, allow_stored: Optional[Union[str, int]] = None) -> str:
    if overwrite_output:
        return overwrite_output

    if config_clear_screen:
        clear()

    print(question + "\n")
    for i, (val, tldr, detail) in enumerate(values):
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

    choice = get_input("", allowed)
    if choice == "":
        choice = str(default)

    elif choice == "s" and allow_stored is not None:
        return str(allow_stored)

    return choice


def authentication_prompt() -> None:
    prev_choice = config_helper.get_user()

    if prev_choice is not None:
        prev_choice = User.sanitize_name(prev_choice)

    if prev_choice == "":
        prev_choice = None

    choice = generic_prompt("There are three ways of storing your password.", [
        ("Encrypted in the database", "Uses the password itself or an optional, additional, password to encrypt your login information.",
         "If you like entering your password this option is for you."),
        ("Clear text in the database", "Your login information is stored in a SQLite Database.",
         f"The password is stored in {path(database_file_location)}\n"
         "It is pretty hard to find and then programmatically extract passwords from a database.\n"
         "So your passwords should be safe."),
        ("Manually entering the information every time", "No passwords are stored. Enter your username every time on demand.", "Use this when you want maximum security and are paranoid."),
    ], default=0, overwrite_output="", allow_stored=prev_choice)

    if choice == "2" or choice == prev_choice:
        return

    print("Please provide authentication for ISIS.")
    username = input("Username: ")
    password = getpass("Password: ")

    config_helper.set_user(username)
    if choice == "0":
        print()
        enc_password = getpass("Additional Password (may be empty): ")
        if enc_password == "":
            enc_password = password

        password = encryptor(enc_password, password)
        config_helper.set_encrypted_password(password)

    else:
        config_helper.set_clear_password(password)


def filename_prompt() -> None:
    prev_choice = config_helper.get_filename_scheme()

    forbidden_chars = "/"
    if is_windows:
        forbidden_chars = "<>:\"/\\|?*"

    choice = generic_prompt(r"""Some programs and programming languages have restrictions
or inconveniences when working with specific characters.

To combat this you can enable a "safe"-mode for the file names.


Once enabled it is not possible to switch back without re-downloading every file.
""", [
        ("No replacing.", f"All characters except {forbidden_chars!r} are left as they are.", ""),
        ("Delete all special characters.",
         "Only ASCII letters + digits + \".\" + \"-\" are allowed. .\n", "When deleting spaces the next character is capitalized."),

    ], default=int(config_helper.default_filename_scheme()), overwrite_output="", allow_stored=prev_choice)

    config_helper.set_filename_scheme(choice)

    print()


def throttler_prompt() -> None:
    prev_choice = config_helper.get_throttle_rate()

    choice = generic_prompt("""If you wish you can throttle your download speed to a limit.
Do you want to do so?

Note: You may overwrite this option by setting the `-d, --download-rate` flag.""", [
        ("No", "", ""),
        ("Yes", "", ""),

    ], default=0, overwrite_output="", allow_stored=prev_choice)

    amount = None
    if choice == "1":
        while True:
            print()
            try:
                amount = input("How many MiB/s am I allowed to consume? ")
                break
            except ValueError:
                clear()
                print("I did not quite catch that\n")

    config_helper.set_throttle_rate(amount)

    print()


def cron_prompt() -> None:
    if is_windows:
        return

    from crontab import CronTab

    cron_works = True
    try:
        with CronTab(user=True) as cron:
            values = [
                ("No", "", ""),
                ("1 Hour", "", ""),
                ("24 Hours", "", ""),
            ]
            command = next(cron.find_command("isisdl"), None)
            if command is not None:
                values.append(("No, but remove the Cron-Job", "", ""))

    except Exception:
        cron_works = False
        values = [
            ("No", "", ""),
        ]

    prompt = "[Linux only]\n\nDo you want me to schedule a Cron-Job to run `isisdl` every x hours?"

    if not cron_works:
        prompt += "\n\nERROR: I could not detect a working Cron-installation.\nThis feature is currently limited to Cron only.\nIn the future there might be support for Systemd timers."

    elif config_helper.get_throttle_rate() is None:
        prompt += "\n\nOn the next page there is a option to throttle your download speed.\nIt is recommended that, if you select a Cron-Job also select a throttle rate."

    choice = generic_prompt(prompt, values, default=0, overwrite_output="")

    if choice == "0":
        return

    with CronTab(user=True) as cron:
        command = next(cron.find_command("isisdl"), None)
        if is_testing:
            return

        if choice == "3" and command is not None:
            cron.remove(command)
            print("Cron-Job erased!")
            return

        if command is not None:
            cron.remove(command)

        import isisdl.__main__
        # Use the executable to have the environment "baked into the interpreter"
        job = cron.new(sys.executable + " " + isisdl.__main__.__file__, "isisdl autogenerated", user=True)

        if choice == "1":
            job.setall("@hourly")
        else:
            job.setall("@daily")

    print()


def telemetry_data_prompt() -> None:
    choice = generic_prompt("""In order to ensure that all courses are downloaded correctly I would like to
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
""", [
        ("No", "", ""),
        ("Yes", "", ""),

    ], default=config_helper.default_telemetry(), overwrite_output="")

    config_helper.set_telemetry(choice)


def update_policy_prompt() -> None:
    prev_choice = config_helper.get_update_policy()
    choice = generic_prompt("""Do you want me to auto-install updates when available?""", [
        ("No", "Do not install any updates.", ""),
        ("Install from github", "",
         "The version of Github is by design always more recent than the one on pip.\n"
         "It should have no stability issues since the update is only downloaded once it passes the tests."),
        ("Install from pip", "", "This build should be always working. Usually pushed ~7-14 days after github release."),
    ], default=int(config_helper.default_update_policy()), overwrite_output="", allow_stored=prev_choice)

    config_helper.set_update_policy(choice)


def main() -> None:
    print(f"""I will guide you through a short configuration phase of about 4min.
It is recommended that you read the options carefully.

If you want to {'accept' if is_first_time else 'reset to'} the default press [d] and [enter].
Otherwise just press [enter].
    """)
    choice = input("")

    if choice.lower() == "d":
        print(f"\n{'Accepted' if is_first_time else 'Reset to'} the defaults!")
        return

    authentication_prompt()
    filename_prompt()
    cron_prompt()
    throttler_prompt()
    update_policy_prompt()
    telemetry_data_prompt()

    print("Thank you for your time - everything is saved!")


if __name__ == "__main__":
    main()
