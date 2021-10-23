#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import datetime
import enum
import inspect
import logging
import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from functools import wraps
from queue import PriorityQueue
from threading import Thread
from typing import Union, Dict, Callable, Optional, cast, List, Tuple, Iterable, Any

import requests
from bs4 import BeautifulSoup

import isis_dl.backend.api as api
from isis_dl.share.settings import working_dir_location, checksum_algorithm, sleep_time_for_isis, download_chunk_size, progress_bar_resolution, ratio_to_skip_big_progress, \
    whitelist_file_name_location, \
    blacklist_file_name_location, log_file_location, is_windows, log_clear_screen


def get_args():
    def check_positive(value):
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    parser = argparse.ArgumentParser(prog="isisdl", formatter_class=argparse.RawTextHelpFormatter, description="""
    This programs downloads all courses from your ISIS page.""")

    parser.add_argument("-v", "--verbose", help="Set the verbosity level", choices=("debug", "info", "warning", "error"), default="info")
    parser.add_argument("-n", "--num-threads", help="The number of threads which download the content from an individual course. (This is multiplied by the number of courses)", type=check_positive,
                        default=8)

    parser.add_argument("-o", "--overwrite", help="Overwrites all existing files i.e. re-downloads them all.", action="store_true")  # TODO
    parser.add_argument("-f", "--file-list", help="The the downloaded files in a summary at the end.\nThis is meant as a debug feature.", action="store_true")  # TODO
    parser.add_argument("-s", "--status-time", help="Set the time (in s) for the status to be updated.", type=float, default=1)
    parser.add_argument("-l", "--log", help="Dump the output to the logfile", action="store_true")

    parser.add_argument("-W", "--whitelist", help="A whitelist of course ID's. ", type=int, nargs="*")
    parser.add_argument("-B", "--blacklist", help="A blacklist of course ID's. Blacklist takes precedence over whitelist.", type=int, nargs="*")

    # Crypt options
    parser.add_argument("-p", "--prompt", help="Force the encryption prompt.", action="store_true")
    parser.add_argument("-c", "--clear", help="Stores the password in clear text (pickle bytes).\nIf you want to live dangerously, enable this option.\n"
                                              "If the -s / --store flag is not set, this option will be ignored silently.", action="store_true")
    parser.add_argument("-L", "--login-info", help="Provide two arguments <[username], [password]>. Uses these as authentication", nargs=2, default=None)

    # Checksum options
    parser.add_argument("-t", "--test-checksums", help="Builds the checksums of all existent files and exits. Then checks if any collisions occurred.\nThis is meant as a debug feature.",
                        action="store_true")
    parser.add_argument("-b", "--build-checksums", help="Builds the checksums of all existent files and exits", action="store_true")
    parser.add_argument("-u", "--unzip", help="Unzips existing zipfiles and exists.", action="store_true")  # TODO: Does this work?

    the_args = parser.parse_known_args()[0]

    # Store the white- / blacklist in args such that it only has to be evaluated once
    def make_list_from_file(filename: str) -> List[int]:
        try:
            with open(path(filename)) as f:
                return [int(item.strip()) for item in f.readlines() if item]
        except FileNotFoundError:
            return []

    whitelist = make_list_from_file(whitelist_file_name_location)
    blacklist = make_list_from_file(blacklist_file_name_location)

    whitelist.extend(the_args.whitelist or [])
    blacklist.extend(the_args.blacklist or [])

    the_args.whitelist = whitelist or [True]
    the_args.blacklist = blacklist

    return the_args


def get_logger(debug_level: Optional[int] = None):
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

    logger = logging.getLogger(__name__)
    logger.propagate = False

    debug_level = debug_level or getattr(logging, args.verbose.upper())
    logger.setLevel(debug_level)

    # File handling
    if args.log:
        fh = logging.FileHandler(path(log_file_location))
        fh.setLevel(debug_level)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(formatter)

        logger.addHandler(fh)

    if not is_windows and False:
        # Add a colored console handler. This only works on UNIX, however I use that. If you don't maybe reconsider using windows :P
        import coloredlogs

        coloredlogs.install(level=debug_level, logger=logger, fmt="%(asctime)s - [%(levelname)s] - %(message)s")

    else:
        # Windows users don't have colorful logs :(
        # Legacy solution that should work for windows.
        #
        # Warning: This is untested.
        #   I think it should work but if not, feel free to submit a bug report!

        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(debug_level)

        console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
        ch.setFormatter(console_formatter)

        logger.addHandler(ch)

    logger.info("Starting up…")

    return logger


def path(*args) -> str:
    return os.path.join(working_dir_location, *args)


def sanitize_name_for_dir(name: str) -> str:
    return name.replace("/", "-")


def clear_screen():
    if not log_clear_screen:
        return

    os.system("cls") if is_windows else os.system("clear")


# Adapted from https://stackoverflow.com/a/5929165 and https://stackoverflow.com/a/36944992
def debug_time(str_to_put: Optional[str] = None, func_to_call: Optional[Callable[[object], str]] = None, debug_level: int = logging.DEBUG):
    def decorator(function):
        @wraps(function)
        def _self_impl(self, *method_args, **method_kwargs):
            logger.log(debug_level, f"Starting: {str_to_put if func_to_call is None else func_to_call(self)}")
            s = time.time()

            method_output = function(self, *method_args, **method_kwargs)
            logger.log(debug_level, f"Finished: {str_to_put if func_to_call is None else func_to_call(self)} in {time.time() - s:.3f}s")

            return method_output

        def _impl(*method_args, **method_kwargs):
            logger.log(debug_level, f"Starting: {str_to_put}")
            s = time.time()

            method_output = function(*method_args, **method_kwargs)
            logger.log(debug_level, f"Finished: {str_to_put} in {time.time() - s:.3f}s")

            return method_output

        if "self" in inspect.getfullargspec(function).args:
            return _self_impl

        return _impl

    return decorator


class MySession(requests.Session):
    def __init__(self, key: str):
        super().__init__()
        self.key = key

    def __str__(self):
        return f"Session with {self.key}"

    def __repr__(self):
        return self.__str__()


class OnKill:
    _funcs: PriorityQueue[Tuple[int, Callable[[], None]]] = PriorityQueue()
    _min_priority = 0
    _already_killed = False

    def __init__(self):
        signal.signal(signal.SIGHUP, OnKill.exit)
        signal.signal(signal.SIGINT, OnKill.exit)
        signal.signal(signal.SIGQUIT, OnKill.exit)
        signal.signal(signal.SIGABRT, OnKill.exit)
        signal.signal(signal.SIGTERM, OnKill.exit)

    @staticmethod
    def add(func, priority: Optional[int] = None):
        if priority is None:
            # Generate a new priority → max priority
            priority = OnKill._min_priority - 1

        OnKill._min_priority = min(priority, OnKill._min_priority)

        OnKill._funcs.put((priority, func))

    @staticmethod
    @atexit.register
    def exit(sig_=None, frame=None):
        logger = get_logger()  # Get a new logger since, on windows, @atexit does (apparently) not maintain the global variables
        if OnKill._already_killed:
            logger.info("Alright, stay calm. I am skipping cleanup and exiting! This *will* lead to corrupted files!")
            os._exit(1)

        if sig_ is not None:
            sig = signal.Signals(sig_)
            logger.warning(f"Noticed signal {sig.name} ({sig.value}). Cleaning up…")
            logger.debug("If you *really* need to exit please send another signal!")

        else:
            logger.info("Shutting down…")

        OnKill._already_killed = True
        for _ in range(OnKill._funcs.qsize()):
            priority, func = OnKill._funcs.get_nowait()
            func()


def on_kill(priority: Optional[int] = None):
    def decorator(function):
        # Expects the method to have *no* args
        @wraps(function)
        def _impl(*_):
            return function()

        OnKill.add(_impl, priority)
        return _impl

    return decorator


OnKill()


class MediaType(enum.Enum):
    video = enum.auto()
    archive = enum.auto()
    document = enum.auto()

    @property
    def dir_name(self):
        if self == MediaType.video:
            return "Videos/"
        elif self == MediaType.archive:
            return "Archives/"
        else:
            return "Material/"

    @staticmethod
    def list_dirs() -> Iterable[str]:
        return "Videos/", "Material/", "Archives/"

    @staticmethod
    def list_excluded_dirs() -> Iterable[str]:
        return "UnpackedArchives",


class DownloadStatus(enum.Enum):
    not_started = enum.auto()
    started = enum.auto()
    succeeded = enum.auto()

    found_by_checksum = enum.auto()
    suspended = enum.auto()
    failed = enum.auto()

    stopped_done = enum.auto()
    force_stopped = enum.auto()

    @property
    def done(self):
        # Canonically done → not forced
        return self in {DownloadStatus.succeeded, DownloadStatus.found_by_checksum, DownloadStatus.failed}

    @property
    def done_or_stopped(self):
        return self in {DownloadStatus.succeeded, DownloadStatus.found_by_checksum, DownloadStatus.failed, DownloadStatus.force_stopped, DownloadStatus.stopped_done}  # O(1) lookup time goes brr

    @property
    def downloading(self):
        # Will eventually download
        return self in {DownloadStatus.not_started, DownloadStatus.started, DownloadStatus.suspended}

    @staticmethod
    def make_progress_bar(item: MediaContainer):
        start, end = "╶", "╴"

        def chop_to_last_10(num: Optional[float]) -> Optional[int]:
            if num is None:
                return None

            return int(num * progress_bar_resolution)

        progress = chop_to_last_10(item.percent_done)

        string = start
        if progress is None:
            string += "~" * progress_bar_resolution

        else:
            string += "█" * progress + " " * (progress_bar_resolution - progress)

        string += end

        return string


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


# TODO: No update when nothing can be displayed
class Status(Thread):
    _instance = None
    _running = True

    def __new__(cls):
        # Singleton
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, files: Optional[List[MediaContainer]] = None):
        self.files = files or []
        super().__init__()
        self.daemon = True
        self.start()

    def add_files(self, files: List[MediaContainer]):
        self.files.extend(files)

    def run(self) -> None:
        while Status._running:
            time.sleep(args.status_time)
            if not self.files:
                continue
            clear_screen()
            # Gather information
            skipped, failed, exited, currently_downloading, finished = [], [], [], [], []

            for item in self.files:
                if item.status.done_or_stopped:
                    finished.append(item)

                if item.status == DownloadStatus.found_by_checksum:
                    skipped.append(item)

                if item.status == DownloadStatus.stopped_done:
                    exited.append(item)

                if item.status == DownloadStatus.failed:
                    failed.append(item)

                if item.status == DownloadStatus.started:
                    currently_downloading.append(item)

            def format_int(num: int):
                # log_10(num) = number of numbers
                return f"{num:{' '}>{math.ceil(math.log10(len(self.files) or 1))}}"

            def format_lst(lst: List[Any]):
                return format_int(len(lst)) + " " * (len(format_int(len(self.files))) + 3)

            logger.info(
                "\n -- Status --\n" +
                f"Finished: {format_int(len(finished))} / {format_int(len(self.files))} files\n" +
                f"Skipped:  {format_lst(skipped)} files (Checksum)\n" +
                f"Skipped:  {format_lst(exited)} files (Exit)\n" +
                f"Failed:   {format_lst(failed)} files"
            )

            # Now determine the the already downloaded amount and display it
            if currently_downloading:
                done: List[Tuple[Union[int, float], str]] = [HumanBytes.format(num.already_downloaded) for num in currently_downloading]  # type: ignore
                first = e_format([num[0] for num in done])
                first_units = [item[1] for item in done]

                max_values: List[Tuple[Union[int, float], str]] = [HumanBytes.format(num.size) for num in currently_downloading]  # type: ignore
                second = e_format([num[0] for num in max_values])
                second_units = [item[1] if item[0] is not None else '   ' for item in max_values]

                progress_str = [item.status.make_progress_bar(item) for item in currently_downloading]

                final_str = f"Currently downloading: {len(currently_downloading)} files\n\n"

                final_middle = [
                    (container.percent_done or 0, f"{progress} [{already} {already_unit} / {size} {size_unit}] - {container.name}")

                    for container, already, already_unit, size, size_unit, progress in
                    zip(currently_downloading, first, first_units, second, second_units, progress_str)
                ]

                final_str += "\n".join(item[1] for item in sorted(final_middle, key=lambda x: x[0], reverse=True))

                # Maybe pad to num_threads of rows
                if len(skipped) / len(self.files) < ratio_to_skip_big_progress:
                    final_str += "\n" * (args.num_threads - len(currently_downloading) + 1)

                if exited:
                    logger.info("Please wait for shutdown…")
                    logger.info(final_str)
                else:
                    logger.debug(final_str)

    @staticmethod
    @on_kill(-1)
    def finish():
        Status._running = False


# Copied and adapted from https://stackoverflow.com/a/63839503
class HumanBytes:
    @staticmethod
    def format(num: Union[int, float, None]) -> Tuple[Optional[float], str]:
        """
        Human-readable formatting of bytes, using binary (powers of 1024) representation.

        Note: num > 0
        Will
            return None <=> num == None
        """

        if num is None:
            return None, "None"

        unit_labels = ["  B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
        last_label = unit_labels[-1]
        unit_step = 1024
        unit_step_thresh = unit_step - 0.5

        unit = None
        for unit in unit_labels:
            if num < unit_step_thresh:
                # Only return when under the rounding threshhold
                break
            if unit != last_label:
                num /= unit_step

        return num, unit


def e_format(
        nums: List[Union[int, float, str, None]],
        precision=2,
        ab: Optional[bool] = None,  # True = Remove - from output | False = Space others accordingly
        direction: str = ">",

        convert_func: Callable[[str], str] = lambda _: str(_)
) -> List[str]:
    #
    if ab is True:
        nums = [n if type(n) == str else abs(n) for n in nums]  # type: ignore

    # Convert the nums → strings
    final = []
    for num in nums:
        if num is None:
            final.append("None")
        if isinstance(num, str):
            final.append(convert_func(num))
        elif isinstance(num, (float, int)):
            final.append(f"{num:.{precision}f}")

    max_len = max([len(item) for item in final])

    # Pad the strings
    final = [f"{item:{' '}{direction}{max_len}}" for item in final]

    return final


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
    status: DownloadStatus = DownloadStatus.not_started
    already_downloaded: int = 0

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
    def from_url(cls, s: MySession, url: str, parent_course, session_key: Optional[str] = None):
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
                logger.warning(f"The folder {folder_id} from {url = } (Course: {parent_course}) could not be downloaded.\nReason: {running_dl.reason}")
                return

            filename = running_dl.headers["content-disposition"].split("filename*=UTF-8\'\'")[-1].strip('"')
            media_type = MediaType.archive

        elif "mod/resource" in url:
            # Follow the link and get the file
            req = s.get(url, allow_redirects=False)

            if req.status_code != 303:
                # TODO: Still download the content
                logger.warning(f"The {url = } (Course = {parent_course}) does not redirect.  I am going to ignore it!")
                return

            redirect = BeautifulSoup(req.text)

            links = redirect.find_all("a")
            if len(links) > 1:
                logger.warning(f"I've found {len(links) = } (Course = {parent_course}) many links. This should be debugged!")

            url = links[0].attrs["href"]
            filename = MediaContainer.name_from_url(url)

        if filename is None:
            logger.warning(f"The filename is None. (Course = {parent_course}) This is probably a bug. Please investigate!\n{url = }")
            filename = "Did not find filename - " + checksum_algorithm(os.urandom(64)).hexdigest()

        return cls(media_type, parent_course, s, url, filename, running_download=running_dl)

    def download(self) -> None:
        if self.status == DownloadStatus.stopped_done:
            return

        if not self.status.not_started:
            logger.warning(f"You have prompted a download of a already started / finished file. This could be a bug! {self.status = }")
            return

        self.status = DownloadStatus.suspended
        if self.running_download is None:
            while True:
                try:
                    self.running_download = self.s.get(self.url, stream=True)
                    break
                except requests.exceptions.ConnectionError:
                    logger.warning(f"ISIS is complaining about the number of downloads (I am ignoring it). Maybe consider dropping the thread count. Sleeping for {sleep_time_for_isis}s.")
                    time.sleep(sleep_time_for_isis)

        self.status = DownloadStatus.started

        if not self.running_download.ok:
            logger.error(f"The running download ({self}) is not okay: Status: {self.running_download.status_code} - {self.running_download.reason} "
                         f"(Course: {self.parent_course.name}). Aborting!")
            self.status = DownloadStatus.failed
            return

        self.hash, chunk = self.parent_course.checksum_handler.maybe_get_chunk(self.running_download.raw, self.name)

        if chunk is None:
            self.status = DownloadStatus.found_by_checksum
            return

        with open(self.parent_course.path(self.media_type.dir_name, self.name), "wb") as f:
            f.write(chunk)
            remaining = self.size
            if remaining is not None:
                remaining -= len(chunk)

            # TODO: Maybe performance is better if we read entire file?
            while remaining is None or remaining > 0:
                if self.status == DownloadStatus.force_stopped:
                    self.status = DownloadStatus.stopped_done
                    return

                new = self.running_download.raw.read(download_chunk_size)
                if len(new) == 0:
                    # No file left
                    break

                self.already_downloaded += len(new)
                if remaining is not None:
                    remaining -= len(new)

                f.write(new)

        self.status = DownloadStatus.succeeded
        self.running_download = None

        # Only register the hash after successfully downloading the file
        self.parent_course.checksum_handler.add(self.hash)

    def stop_download(self, tried_previously: bool = False):
        if self.status == DownloadStatus.not_started:
            self.status = DownloadStatus.force_stopped if tried_previously else DownloadStatus.stopped_done

    @property
    def size(self) -> Optional[int]:
        if self.running_download is None:
            return None
        try:
            return int(self.running_download.headers["content-length"])
        except KeyError:
            return None

    @property
    def percent_done(self) -> Optional[float]:
        if self.running_download is None or self.size is None:
            return None
        try:
            return self.already_downloaded / self.size
        except KeyError:
            return None

    def __lt__(self, other):
        try:
            self.percent_done < other.percent_done
        except TypeError:
            # If they aren't comparable by percent do it by name
            return self.name < other.name

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"[{HumanBytes.format(self.already_downloaded)} / {HumanBytes.format(self.size)}] \t {self}"


args = get_args()
logger = get_logger()
status = Status()
