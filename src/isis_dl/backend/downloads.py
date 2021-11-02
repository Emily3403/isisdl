"""
This file is concerned with how to download an actual file given an url.
"""
from __future__ import annotations

import datetime
import enum
import math
import os
import time
from dataclasses import dataclass, field
from queue import Full, Queue, Empty
from threading import Thread
from typing import Optional, List, Any, Iterable, Dict, cast, Tuple, Union, BinaryIO

import requests
from bs4 import BeautifulSoup

from isis_dl.backend import api
from isis_dl.share.settings import progress_bar_resolution, checksum_algorithm, download_chunk_size, token_queue_refresh_rate, print_status
from isis_dl.share.utils import HumanBytes, clear_screen, args, logger, e_format, on_kill, sanitize_name_for_dir


class SessionWithKey(requests.Session):
    def __init__(self, key: str):
        super().__init__()
        self.key = key

    def __str__(self):
        return f"Session with {self.key}"

    def __repr__(self):
        return self.__str__()


# Represents a granted token. A download may only download as much as defined in num_bytes.
@dataclass
class Token:
    num_bytes: int = download_chunk_size


class DownloadThrottler(Thread):
    """
    This class acts in a way that the download speed is capped at a certain maximum.
    It does so by handing out tokens, which are limited. With every token you may download a `download_chunk_size`.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.active_tokens: Queue[Token] = Queue()
        self.used_tokens: Queue[Token] = Queue()

        for _ in range(self.max_tokens()):
            self.active_tokens.put(Token())

        self.start()

    def run(self) -> None:
        # num has to be distributed over `token_queue_refresh_rate` seconds
        num = DownloadThrottler.max_tokens()

        while True:
            start = time.time()
            try:
                for _ in range(num):
                    self.active_tokens.put(self.used_tokens.get())

            except (Full, Empty):
                pass

            time.sleep(max(token_queue_refresh_rate - (time.time() - start), 0))

    def get(self):
        token = self.active_tokens.get()
        self.used_tokens.put(token)

        return token

    @staticmethod
    def max_tokens() -> int:
        return int(args.download_rate * 1024 ** 2 // download_chunk_size * token_queue_refresh_rate)


class DownloadStatus(enum.Enum):
    not_started = enum.auto()
    downloading = enum.auto()
    suspended = enum.auto()
    succeeded = enum.auto()
    failed = enum.auto()

    # Special states
    found_by_checksum = enum.auto()
    stopped = enum.auto()
    stopped_done = enum.auto()

    @property
    def done(self):
        return self in {DownloadStatus.succeeded, DownloadStatus.found_by_checksum, DownloadStatus.failed, DownloadStatus.stopped_done}  # O(1) lookup time goes brr

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


@dataclass
class MediaContainer:
    media_type: MediaType
    parent_course: api.Course
    s: SessionWithKey
    url: str
    name: str
    size: Optional[int] = None
    date: Optional[datetime.datetime] = None
    additional_params_for_request: Dict[str, str] = field(default_factory=lambda: {})
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
    def from_video(cls, s: SessionWithKey, video: Dict[str, str], parent_course):
        timestamp = datetime.datetime.fromtimestamp(cast(int, video["timecreated"]))
        return cls(MediaType.video, parent_course, s, video["url"], video["title"] + video["fileext"], date=timestamp)

    @classmethod
    def from_url(cls, s: SessionWithKey, url: str, parent_course, session_key: Optional[str] = None):
        if "isis" not in url:
            # Don't go downloading other stuff.
            return

        elif any(item in url for item in ["mod/url", "mod/page", "mod/forum"]):
            # These links dont lead to actual files. Ignore them
            return

        filename, media_type, additional_kwargs = None, MediaType.document, {}

        if "mod/folder" in url:
            folder_id = url.split("id=")[-1]
            # Use the POST form
            req = s.head("https://isis.tu-berlin.de/mod/folder/download_folder.php", params={"id": folder_id, "sesskey": session_key})
            if not req.ok:
                logger.warning(f"The folder {folder_id} from {url = } (Course: {parent_course}) could not be downloaded.\nReason: {req.reason}")
                return

            filename = req.headers["content-disposition"].split("filename*=UTF-8\'\'")[-1].strip('"')
            media_type = MediaType.archive
            url = "https://isis.tu-berlin.de/mod/folder/download_folder.php"
            additional_kwargs = {"id": folder_id, "sesskey": session_key}


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

        # Read the size from url
        try:
            size = int(s.head(url).headers["content-length"])
        except KeyError:
            size = None

        return cls(media_type, parent_course, s, url, filename, size, additional_params_for_request=additional_kwargs)

    def download(self) -> None:
        if self.status != DownloadStatus.not_started:
            if self.status == DownloadStatus.stopped:
                self.status = DownloadStatus.stopped_done
            else:
                logger.warning(f"You have prompted a download of an already started / finished file ({self.status = }). This could be a bug! {self.status = }")
            return

        running_download = self.s.get(self.url, stream=True, params=self.additional_params_for_request)
        try:
            self.size = int(running_download.headers["content-length"])
        except KeyError:
            # Some downloads don't define a content-length. That is bad for checksums but nothing I can do…
            pass

        if not running_download.ok:
            logger.error(f"The running download ({self}) is not okay: Status: {running_download.status_code} - {running_download.reason} "
                         f"(Course: {self.parent_course.name}). Aborting!")
            self.status = DownloadStatus.failed
            return

        if (checksum := self.parent_course.checksum_handler.already_downloaded(self)) is None:
            self.status = DownloadStatus.found_by_checksum
            running_download.close()
            return

        self.status = DownloadStatus.downloading

        with open(self.parent_course.path(self.media_type.dir_name, self.name), "wb") as f:
            # TODO: If nothing is downloading, start downloading regardless of checksum

            # We copy in chunks to add the rate limiter and status indicator. This could also be done with `shutil.copyfileobj`.
            while True:
                token = throttler.get()

                new = running_download.raw.read(token.num_bytes)
                if len(new) == 0:
                    # No file left
                    break

                f.write(new)
                self.already_downloaded += len(new)

        self.status = DownloadStatus.succeeded

        # Only register the hash after successfully downloading the file
        self.parent_course.checksum_handler.add(checksum)
        running_download.close()

    def stop_download(self):
        if self.status == DownloadStatus.not_started:
            self.status = DownloadStatus.stopped

    @property
    def percent_done(self) -> Optional[float]:
        try:
            return self.already_downloaded / self.size
        except TypeError:
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
        super().__init__(daemon=True)

        if print_status:
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
                if item.status.done:
                    finished.append(item)

                if item.status == DownloadStatus.found_by_checksum:
                    skipped.append(item)

                if item.status == DownloadStatus.stopped_done:
                    exited.append(item)

                if item.status == DownloadStatus.failed:
                    failed.append(item)

                if item.status == DownloadStatus.downloading:
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

                if exited:
                    logger.info("Please wait for shutdown…")
                    logger.info(final_str)
                else:
                    logger.debug(final_str)

    @staticmethod
    @on_kill(-1)
    def finish():
        Status._running = False


status = Status()
throttler = DownloadThrottler()
