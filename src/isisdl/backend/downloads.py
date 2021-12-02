"""
This file is concerned with how to download an actual file given an url.
"""
from __future__ import annotations

import datetime
import enum
import math
import os
import random
import string
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from queue import Full, Queue, Empty
from threading import Thread
from typing import Optional, List, Any, Iterable, Dict, cast, Tuple, Union

from bs4 import BeautifulSoup
from requests import Session

from isisdl.backend import api
from isisdl.share.settings import progress_bar_resolution, download_chunk_size, token_queue_refresh_rate, print_status, status_time, num_tries_download
from isisdl.share.utils import HumanBytes, clear_screen, args, logger, e_format, on_kill, sanitize_name_for_dir, get_url_from_session, get_head_from_session


class SessionWithKey:
    def __init__(self, s: Session, key: str):
        self.s = s
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
        self.times_get = 0

        for _ in range(self.max_tokens()):
            self.active_tokens.put(Token())

        # Dummy token used to maybe return it all the time.
        self.token = Token()

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
        self.times_get += 1
        if args.download_rate is None:
            self.used_tokens.put(self.token)
            return self.token

        token = self.active_tokens.get()
        self.used_tokens.put(token)

        return token

    @staticmethod
    def max_tokens() -> int:
        if args.download_rate is None:
            return 1

        return int(args.download_rate * 1024 ** 2 // download_chunk_size * token_queue_refresh_rate)


class FailedDownload(enum.Enum):
    link_did_not_redirect = enum.auto()
    empty_folder = enum.auto()
    timeout = enum.auto()
    stopped = enum.auto()

    @property
    def done(self):
        return True

    @property
    def fixable(self):
        return self in {FailedDownload.timeout, FailedDownload.stopped}

    @property
    def reason(self) -> str:
        if self == FailedDownload.link_did_not_redirect:
            return "The link did not redirect."

        if self == FailedDownload.empty_folder:
            return "The folder was empty."

        if self == FailedDownload.timeout:
            return f"The request timed out ({num_tries_download} tried)."

        if self == FailedDownload.stopped:
            return "The download was stopped by the user."

        return ""

    @property
    def fix(self) -> str:
        if self == FailedDownload.link_did_not_redirect:
            return "None. This can only be fixed by a programmer."

        if self == FailedDownload.empty_folder:
            return "None. This cannot be fixed."

        if self == FailedDownload.timeout:
            return "Try to restart me and hope for the best."

        if self == FailedDownload.stopped:
            return "Don't cancel the download"

        return ""


class DownloadStatus(enum.Enum):
    not_started = enum.auto()
    downloading = enum.auto()
    waiting_for_checksum = enum.auto()
    succeeded = enum.auto()

    # Special states
    found_by_checksum = enum.auto()
    # TODO: Migrate to FailedDownload
    stopped = enum.auto()

    @property
    def done(self):
        return self in {DownloadStatus.succeeded, DownloadStatus.found_by_checksum}  # O(1) lookup time goes brr

    @property
    def fixable(self):
        return True


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
    not_found = enum.auto()

    @property
    def dir_name(self):
        if self == MediaType.video:
            return "Videos"
        elif self == MediaType.archive:
            return "Archives"
        else:
            return "Material"

    @staticmethod
    def list_dirs() -> Iterable[str]:
        return "Videos", "Material", "Archives"

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
    status: Union[DownloadStatus, FailedDownload] = DownloadStatus.not_started
    already_downloaded: int = 0
    checksum: Union[str, bool, None] = None

    def __post_init__(self):
        self.name = sanitize_name_for_dir(self.name)

        self.checksum = self.parent_course.checksum_handler.already_downloaded(self)

        if self.checksum is None:
            self.status = FailedDownload.timeout

        elif self.checksum is False:
            self.status = DownloadStatus.found_by_checksum
            self.already_downloaded = self.size or 0

    @staticmethod
    def name_from_url(name: str) -> str:
        return name.split("/")[-1].split("?")[0]

    @staticmethod
    def extract_info_from_header(s: SessionWithKey, url: str, additional_params=None) -> Union[None, Tuple[Optional[int], Optional[datetime.datetime], Optional[str]]]:
        additional_params = additional_params or {}
        # Read the size from url
        req = get_url_from_session(s.s, url, stream=True, params=additional_params)
        if req is None:
            return None

        headers = req.headers
        req.close()

        try:
            size: Optional[int] = int(headers["content-length"])
        except KeyError:
            size = None

        try:
            date: Optional[datetime.datetime] = parsedate_to_datetime(headers["last-modified"])
        except KeyError:
            date = None

        try:
            filename: Optional[str] = MediaContainer.strip_content_disposition(headers["content-disposition"])
        except KeyError:
            filename = None

        return size, date, filename

    @classmethod
    def from_video(cls, s: SessionWithKey, parent_course, video: Dict[str, str]):
        timestamp = datetime.datetime.fromtimestamp(cast(int, video["timecreated"]))
        url = video["url"]
        info = MediaContainer.extract_info_from_header(s, url)
        if info is None:
            cls(MediaType.video, parent_course, s, url, video["title"] + video["fileext"], status=FailedDownload.timeout)
            return

        size, *_ = info

        return cls(MediaType.video, parent_course, s, url, video["title"] + video["fileext"], size, timestamp)

    @classmethod
    def from_url(cls, s: SessionWithKey, parent_course, url: str):
        _temp_name = f"Not-found-{''.join(random.choices(string.digits, k=16))}"

        if "mod/url" in url:
            # Try to follow the redirect. If it is allowed through the black- / whitelist, download it
            req = get_url_from_session(s.s, url)
            if req is None:
                return cls(MediaType.not_found, parent_course, s, url, _temp_name, status=FailedDownload.timeout)

            if req.history:
                url = req.url

            else:
                # Did not redirect → find the link on the ISIS-Page
                req_soup = BeautifulSoup(req.text, features="html.parser")
                url = req_soup.find("div", "urlworkaround").find("a").attrs.get("href")

        if url is None:
            return   # type: ignore

        if any(item in url for item in {"mod/url", "mod/page", "mod/forum", "mod/assign", "mod/feedback", "mod/quiz", "mod/videoservice", "mod/etherpadlite",
                                        "mod/questionnaire", "availability/condition", "mod/lti", "mod/scorm", "mod/choicegroup", "mod/glossary", "mod/choice",
                                        "mod/choicegroup", "mailto:", "tu-berlin.zoom.us", "@campus.tu-berlin.de", "mod/h5pactivity", "meet.isis.tu-berlin.de",
                                        "course/view.php", "mod/ratingallocate"}):
            # These links are definite blacklists on stuff we don't want to follow.
            return

        if "isis" not in url:
            return

        if not any(item in url for item in {"pluginfile.php", "mod/resource", "mod/folder"}):
            # This is a whitelist
            logger.debug(f"This url was ignored but not blacklisted: {url}.")
            return

        filename, media_type, additional_kwargs = None, MediaType.document, {}

        if "mod/folder" in url:
            folder_id = url.split("id=")[-1]
            # Use the POST form
            req = get_head_from_session(s.s, "https://isis.tu-berlin.de/mod/folder/download_folder.php", params={"id": folder_id, "sesskey": s.key})
            if req is None:
                return cls(MediaType.not_found, parent_course, s, url, _temp_name, status=FailedDownload.timeout)

            if not req.ok:
                return cls(MediaType.not_found, parent_course, s, url, _temp_name, status=FailedDownload.link_did_not_redirect)

            filename = req.headers["content-disposition"].split("filename*=UTF-8\'\'")[-1].strip('"')
            name, ext = os.path.splitext(filename)

            filename = name[:-9] + ext
            media_type = MediaType.archive
            url = "https://isis.tu-berlin.de/mod/folder/download_folder.php"
            additional_kwargs = {"id": folder_id, "sesskey": s.key}

        elif "mod/resource" in url:
            # Follow the link and get the file
            req = get_url_from_session(s.s, url, allow_redirects=False)

            name = f"Not-found-{''.join(random.choices(string.digits, k=16))}"
            if req is None:
                return cls(MediaType.not_found, parent_course, s, url, name, status=FailedDownload.link_did_not_redirect)

            if req.status_code != 303:
                # TODO: Still download the content
                return cls(MediaType.not_found, parent_course, s, url, name, status=FailedDownload.link_did_not_redirect)

            redirect = BeautifulSoup(req.text, features="html.parser")

            links = redirect.find_all("a")
            if len(links) > 1:
                logger.debug(f"I've found {len(links) = } (Course = {parent_course}) many links. This should be debugged!")

            url = links[0].attrs["href"]
            filename = MediaContainer.name_from_url(url)

        # Read the size from url
        info = MediaContainer.extract_info_from_header(s, url, additional_kwargs)
        if info is None:
            if filename is None:
                filename = f"Not-found-{''.join(random.choices(string.digits, k=16))}"

            cls(media_type, parent_course, s, url, filename, status=FailedDownload.timeout)
            return

        size, date, _name = info
        if filename is None:
            filename = _name

        if filename is None:
            logger.warning(f"The filename is None. (Course = {parent_course}) This is probably a bug. Please investigate!\n{url = }")
            filename = f"Not-found-{''.join(random.choices(string.digits, k=16))}"

        return cls(media_type, parent_course, s, url, filename, size, date, additional_params_for_request=additional_kwargs)

    def download(self) -> None:
        if self.status != DownloadStatus.not_started:
            if self.status == DownloadStatus.stopped:
                self.status = FailedDownload.stopped
            return

        running_download = get_url_from_session(self.s.s, self.url, stream=True, params=self.additional_params_for_request)
        if running_download is None:
            self.status = FailedDownload.timeout
            return

        try:
            self.size = int(running_download.headers["content-length"])
        except KeyError:
            # Some downloads don't define a content-length. That is bad for checksums but nothing I can do…
            pass

        if not running_download.ok:
            logger.error(f"The running download ({self}) is not okay: Status: {running_download.status_code} - {running_download.reason} "
                         f"(Course: {self.parent_course.name}). Aborting!")
            self.status = FailedDownload.timeout
            return

        self.status = DownloadStatus.waiting_for_checksum

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
        if self.checksum is not None and not isinstance(self.checksum, bool):
            self.parent_course.checksum_handler.add(self.checksum)

        running_download.close()

    def stop_download(self):
        if self.status == DownloadStatus.not_started:
            self.status = DownloadStatus.stopped

    @staticmethod
    def strip_content_disposition(st: str):
        if st.startswith("inline") or "filename=" in st:
            return st.split("filename=")[-1].strip("\"")

        if st.startswith("attachment"):
            if "filename*=" in st:
                return st.split("filename*=UTF-8\'\'")[-1].strip("\'")

        logger.error(f"Error decoding {st}: Did not find a valid transformation.")

    @property
    def percent_done(self) -> Optional[float]:
        if self.size is None:
            return None

        return self.already_downloaded / self.size

    def __lt__(self, other):
        try:
            self.percent_done < other.percent_done
        except TypeError:
            # If they aren't comparable by percent do it by name
            return self.name < other.name

    def __hash__(self):
        if not isinstance(self.checksum, str):
            return random.randint(0, 2 ** 15)
        return int("0x" + self.checksum, 0)

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.name == other.name

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"[{HumanBytes.format(self.already_downloaded)} / {HumanBytes.format(self.size)}] \t {self}"

    def error_format(self):
        if not isinstance(self.status, FailedDownload):
            return self.name

        lf = "\n" + " " * 8
        final_str = self.name + ":" + lf + "Name:     " + self.name + lf + "Course:   " + self.parent_course.name + lf + "Url:      " + self.url
        final_str += lf + "Reason:   " + self.status.reason + lf * 2 + "Possible fix: " + self.status.fix + "\n"
        return final_str


class Status(Thread):
    _instance = None
    _running = True
    sum_file_sizes = 0

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
        Status.sum_file_sizes += sum(item.size if item.size is not None else 0 for item in files)

    def run(self) -> None:
        while Status._running:
            time.sleep(status_time)
            if not self.files:
                continue

            if Status._running:
                clear_screen()
            # Gather information
            skipped, failed, exited, currently_downloading, finished = [], [], [], [], []

            for item in self.files:
                if item.status.done:
                    finished.append(item)

                if item.status == DownloadStatus.found_by_checksum:
                    skipped.append(item)

                if item.status == FailedDownload.stopped:
                    exited.append(item)

                elif isinstance(item.status, FailedDownload):
                    failed.append(item)

                if item.status == DownloadStatus.downloading:
                    currently_downloading.append(item)

            def format_int(num: int):
                # log_10(num) = number of numbers
                return f"{num:{' '}>{math.ceil(math.log10(len(self.files) or 1))}}"

            def format_lst(lst: List[Any]):
                return format_int(len(lst)) + " " * (len(format_int(len(self.files))) + 3)

            if args.download_rate is None:
                bandwidth_usage = "\n"
            else:
                curr_download_usage, curr_download_unit = HumanBytes.format(throttler.used_tokens.qsize() * download_chunk_size / token_queue_refresh_rate)
                bandwidth_usage = f"Current bandwidth usage: {curr_download_usage:.2f} {curr_download_unit}/s\n\n"

            amount_downloaded, amount_downloaded_unit = HumanBytes.format(sum(item.already_downloaded for item in self.files))
            amount_downloaded_max, amount_downloaded_max_unit = HumanBytes.format(Status.sum_file_sizes)

            if Status._running:
                logger.info(
                    "\n -- Status --\n\n" +
                    f"Downloaded {amount_downloaded:.2f} {amount_downloaded_unit} / {amount_downloaded_max:.2f} {amount_downloaded_max_unit}\n" +
                    bandwidth_usage +
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

                progress_str = [make_progress_bar(item) for item in currently_downloading]

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

    @staticmethod
    @on_kill(-1)
    def finish():
        Status._running = False


status = Status()
throttler = DownloadThrottler()
