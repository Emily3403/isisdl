#!/usr/bin/env python3
from __future__ import annotations
import datetime
import enum
import platform
import logging
import argparse
import shutil
import sys
import os
import time
import inspect
import zipfile

from dataclasses import dataclass
from functools import wraps
from typing import Union, Dict, Callable, Optional, cast

import requests
from bs4 import BeautifulSoup

from isis_dl.share.settings import working_dir, temp_dir, checksum_algorithm, sleep_time_for_isis
import isis_dl.backend.api as api


def get_args():
    def check_positive(value):
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This programs downloads all courses from your ISIS page.""")

    parser.add_argument("-l", "--logging", help="Set the debug level", choices=("debug", "info", "warning", "error"), default="info")
    parser.add_argument("-n", "--thread-num", help="The number of threads which download the content from an individual course. (This is multiplied by the number of courses)", type=check_positive,
                        default=10)

    parser.add_argument("-o", "--overwrite", help="Overwrites all existing files i.e. re-downloads them all.", action="store_true")  # TODO
    parser.add_argument("-u", "--unzip", help="Does *not* unzip the zipped files.", action="store_true", default=True)  # TODO: Does this work?

    # Crypt options
    parser.add_argument("-p", "--prompt", help="Force the encryption prompt.", action="store_true")
    parser.add_argument("-c", "--clear", help="Stores the password in clear text (pickle bytes).\nIf you want to live dangerously, enable this option.\n"
                                              "If the -s / --store flag is not set, this option will be ignored silently.", action="store_true")
    parser.add_argument("-L", "--login-info", help="Uses this information as login information to ISIS.", nargs=2, default=None)

    # Checksum options
    parser.add_argument("-t", "--test-checksums", help="Builds the checksums of all existent files. Then checks if any collisions occurred.\nThis is meant as a debug feature.", action="store_true")
    parser.add_argument("-b", "--build-checksums", help="Builds the checksums of all existent files. Exits afterwards.", action="store_true")

    parser.add_argument("-f", "--file-list", help="The the downloaded files in a summary at the end.\nThis is meant as a debug feature.", action="store_true")
    return parser.parse_known_args()[0]


args = get_args()


def create_logger(debug_level: Optional[int] = None):
    """
    Creates the logger
    """
    # disable DEBUG messages from various modules
    logging.getLogger("urllib3").propagate = False
    logging.getLogger("selenium").propagate = False
    logging.getLogger("matplotlib").propagate = False
    logging.getLogger("PIL").propagate = False
    logging.getLogger("oauthlib").propagate = False
    logging.getLogger("requests_oauthlib.oauth1_auth").propagate = False

    logger = logging.getLogger()

    debug_level = debug_level or getattr(logging, args.logging.upper())
    logger.setLevel(debug_level)

    if platform.system() != "Windows":
        # Add a colored console handler. This only works on UNIX, however I use that. If you don't maybe reconsider using windows :P
        import coloredlogs
        coloredlogs.install(level=debug_level, fmt='%(asctime)s [%(levelname)s] %(message)s')
    else:
        # Windows users don't have colorful logs :(
        # Legacy solution that should work for windows.
        #
        # Warning:
        #   This is untested.
        #   I think it should work but if not, feel free to submit a bug report!

        ch = logging.StreamHandler(stream=sys.stdout)
        console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
        ch.setLevel(debug_level)
        ch.setFormatter(console_formatter)
        logger.addHandler(ch)

    logging.info("Starting up…")

    return logger


def path(*args) -> str:
    return os.path.join(working_dir, *args)


def sanitize_name_for_dir(name: str) -> str:
    return name.replace("/", "-")


# Adapted from https://stackoverflow.com/a/5929165 and https://stackoverflow.com/a/36944992
def debug_time(str_to_put: Optional[str] = None, func_to_call: Optional[Callable[[object], str]] = None, debug_level=logging.debug):
    def decorator(function):
        @wraps(function)
        def _self_impl(self, *method_args, **method_kwargs):
            debug_level(f"Starting: {str_to_put if func_to_call is None else func_to_call(self)}")
            s = time.time()

            method_output = function(self, *method_args, **method_kwargs)
            debug_level(f"Finished: {str_to_put if func_to_call is None else func_to_call(self)} in {time.time() - s:.3f}s")

            return method_output

        def _impl(*method_args, **method_kwargs):
            debug_level(f"Starting: {str_to_put!r}")
            s = time.time()

            method_output = function(*method_args, **method_kwargs)
            debug_level(f"Finished: {str_to_put!r} in {time.time() - s:.3f}s")

            return method_output

        if "self" in inspect.getfullargspec(function).args:
            return _self_impl

        return _impl

    return decorator


class MediaType(enum.Enum):
    video = enum.auto()
    archive = enum.auto()
    document = enum.auto()

    @property
    def dir_name(self):
        if self == MediaType.video:
            return "Videos/"
        else:
            return "Material/"

    @staticmethod
    def list_dirs():
        return "Videos/", "Material/"


# Shared between modules.
@dataclass
class User:
    username: str
    password: str

    def __repr__(self):
        return f"{self.username}: {self.password}"

    def __str__(self):
        return f"\"{self.username}\""

    def dump(self):
        return self.username + "\n" + self.password + "\n"


@dataclass
class Video:
    name: str
    collection_name: Union[str, None] = None
    url: Union[str, None] = None
    created: Union[str, None] = None
    approximate_filename: Union[str, None] = None

    @classmethod
    def from_dict(cls, content: Dict[str, str]):
        return cls(content["title"], content["collectionname"], content["url"], content["timecreated"])

    def __post_init__(self):
        self.name = sanitize_name_for_dir(self.name)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == other
        return self.__class__ == other.__class__ and self.name == other.name

    def __lt__(self, other):
        if self.__class__ != other.__class__:
            raise ValueError
        if self.created is None:
            if other.created is not None:
                return False
            return self.name > other.name
        return other.created > self.created


@dataclass
class MediaContainer:
    media_type: MediaType
    parent_course: api.Course
    s: requests.Session
    url: str
    name: str
    date: Optional[datetime.datetime] = None
    running_download: Optional[requests.Response] = None
    hash: Optional[str] = None

    def __post_init__(self):
        self.name = sanitize_name_for_dir(self.name)

        if self.date is None:
            self.date = datetime.datetime.now()

    @staticmethod
    def name_from_url(name: str) -> str:
        return name.split("/")[-1].split("?")[0]

    @classmethod
    def from_video(cls, s: requests.Session, video: Dict[str, str], parent_course):
        timestamp = datetime.datetime.fromtimestamp(cast(int, video["timecreated"]))
        return cls(MediaType.video, parent_course, s, video["url"], video["title"] + video["fileext"], date=timestamp)

    @classmethod
    def from_url(cls, s: requests.Session, url: str, parent_course, session_key: Optional[str] = None):
        if "isis" not in url:
            # Don't go downloading other stuff.
            return

        elif any(item in url for item in ["mod/url", "mod/page", "mod/forum"]):
            # These links dont lead to actual files. Ignore them
            return

        filename, media_type, running_dl = None, MediaType.document, None

        if "mod/folder" in url:
            folder_id = url.split("id=")[-1]
            # Use the POST form
            running_dl = s.get("https://isis.tu-berlin.de/mod/folder/download_folder.php", params={"id": folder_id, "sesskey": session_key}, stream=True)
            if not running_dl.ok:
                logging.debug(f"The folder {folder_id} from {url = } could not be downloaded.\nReason: {running_dl.reason}")
                return

            filename = running_dl.headers["content-disposition"].split("filename*=UTF-8\'\'")[-1].strip('"')
            media_type = MediaType.archive

        elif "mod/resource" in url:
            # Follow the link and get the file
            req = s.get(url, allow_redirects=False)

            if req.status_code != 303:
                logging.debug(f"The {url = } does not redirect. I am going to ignore it!")
                return

            redirect = BeautifulSoup(req.text, features="html.parser")

            links = redirect.find_all("a")
            if len(links) > 1:
                logging.debug(f"I've found {len(links) = } many links. This should be debugged!")

            url = links[0].attrs["href"]
            filename = MediaContainer.name_from_url(url)

        if filename is None:
            logging.warning(f"The filename is None. This is probably a bug. Please investigate!\n{url = }")
            filename = "Did not find filename - " + checksum_algorithm(os.urandom(64)).hexdigest()

        # assert filename is not None

        return cls(media_type, parent_course, s, url, filename, running_download=running_dl)

    def download(self) -> bool:
        if self.running_download is None:
            while True:
                try:
                    self.running_download = self.s.get(self.url, stream=True)
                    break
                except requests.exceptions.ConnectionError:
                    logging.warning(f"ISIS is complaining about the number of downloads (I am ignoring it). Maybe consider dropping the thread count. Sleeping for {sleep_time_for_isis}s.")
                    time.sleep(sleep_time_for_isis)

        if not self.running_download.ok:
            logging.error(f"The running download is not okay: {self.running_download.reason}. Aborting!")
            return False

        self.hash, chunk = self.parent_course.checksum_handler.maybe_get_chunk(self.running_download.raw, self.name)

        if chunk is None:
            logging.debug(f"Found {self.name!r} via checksum. Skipping…")
            return False

        logging.debug(f"Started downloading {self.name!r}")

        filename = self.parent_course.path(self.media_type.dir_name, self.name)

        unpack = args.unzip and self.media_type == MediaType.archive
        if unpack:
            _fn = os.path.splitext(filename)[0]
            filename = path(temp_dir, self.name)

        with open(filename, "wb") as f:
            f.write(chunk)
            shutil.copyfileobj(self.running_download.raw, f)

        # Only register the hash after successfully downloading the file
        self.parent_course.checksum_handler.add(self.hash)

        if unpack:
            try:
                shutil.unpack_archive(filename, _fn)
            except (EOFError, zipfile.BadZipFile, shutil.ReadError):
                logging.warning(f"Bad zip file: {self.name}")
                x = zipfile.ZipFile(filename)
                x.extractall(path=_fn)
                print()

        return True
