#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Optional

import requests

from isisdl.backend.utils import config_helper
from isisdl.version import __version__


def check_pypi_for_version() -> Optional[str]:
    # Inspired from https://pypi.org/project/pypi-search
    to_search = requests.get("https://pypi.org/project/isisdl/").text
    version = re.search("<h1 class=\"package-header__name\">\n *(.*)?\n *</h1>", to_search)

    if version is None:
        return None

    groups = version.groups()
    if groups is None or len(groups) != 1:
        return None

    return groups[0].split()[1]


def check_github_for_version() -> Optional[str]:
    badge = requests.get("https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg").text
    if "passing" not in badge:
        return None

    res = requests.get("https://raw.githubusercontent.com/Emily3403/isisdl/main/src/isisdl/version.py")
    if not res.ok:
        return None

    version = re.match("__version__ = \"(.*)?\"", res.text)
    if version is None:
        return None

    return version.group(1)


def install_latest_version() -> None:
    version_github = check_github_for_version()
    version_pypi = check_pypi_for_version()

    update_policy = config_helper.get_or_default_update_policy()
    if update_policy == "0":
        return

    correct_version = version_github if update_policy == "1" else version_pypi

    if correct_version is None:
        return

    if correct_version > __version__:
        print(f"\nThere is a new version available: {correct_version} (current: {__version__}).")
        print("According to your update policy I will auto-install it.\n")

    else:
        return

    if update_policy == "1":
        old_dir = os.getcwd()
        with TemporaryDirectory() as tmp:
            os.chdir(tmp)
            print(f"Cloning the repository into {tmp} ...")
            ret = subprocess.check_call(["git", "clone", "https://github.com/Emily3403/isisdl"])
            if ret:
                print(f"Cloning failed with exit code {ret}")
                return

            print("Installing with pip ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "./isisdl"])
            os.chdir(old_dir)

    if update_policy == "2":
        subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", "isisdl"])
