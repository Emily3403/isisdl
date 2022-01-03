#!/usr/bin/env python3
import re

import requests
from bs4 import BeautifulSoup

from isisdl.share.utils import logger
from isisdl.version import __version__


def check_pypi_for_version() -> str:
    # Inspired from https://pypi.org/project/pypi-search

    soup = BeautifulSoup(requests.get("https://pypi.org/project/isisdl/").text, 'html.parser')
    package_name_header = soup.find('h1', class_='package-header__name')
    version = package_name_header.text.split()[1]

    return str(version)


def check_github_for_version() -> str:
    res = requests.get("https://raw.githubusercontent.com/Emily3403/isisdl/faster_checksum/src/isisdl/version.py")
    if not res.ok:
        logger.error("I could not obtain the latest version. Probably the link, which is hard-coded, is wrong.")
        assert False

    version = re.match("__version__ = \"(.*)?\"", res.text)
    if version is None:
        logger.error("I could not parse the specified version.")
        assert False

    return version.group(1)


def main() -> None:
    version_github = check_github_for_version()
    version_pypi = check_pypi_for_version()

    if __version__ != version_github:
        print(f"\nThere is a new version available: {version_github} (current: {__version__}).")
        if version_pypi == version_github:
            print("You're in luck: The new version is already available on PyPI.\n")
        else:
            print("Unfortunately the new version is not uploaded to PyPI yet.\n")

        possible_choices = {"i", "g"}
        message = """Do you want to:
    [i] ignore this update
    [g] install the new version from github"""

        if version_pypi == version_github:
            message += "    [p] install the new version from PyPI"
            possible_choices.add("p")

        message += "\n"
        print(message)

        already_prompted = False
        while True:

            choice = input("")

            if choice not in possible_choices:
                num = message.count('\n') + 3 + already_prompted
                print(f"\033[{num}A\r")
                print(message)
                print(f"Your response {choice!r} was not in the expected ones {possible_choices!r}.")

                already_prompted = True
                continue

            break

        if choice == "i":
            return

        if choice == "g":
            return

        if choice == "p":
            return


    pass


if __name__ == '__main__':
    main()