"""
This file is concerned with how to download an actual file given an url.
"""

from __future__ import annotations

import datetime
import enum
import shutil
import time
from base64 import standard_b64decode
from dataclasses import dataclass
from pathlib import Path
from queue import Full, Queue, Empty
from threading import Thread
from typing import Optional, List, Any, Iterable, Dict, TYPE_CHECKING, cast, Union

import math
from requests import Session, Response
from requests.exceptions import InvalidSchema

from isisdl.backend.utils import HumanBytes, args, User, calculate_local_checksum, database_helper, config
from isisdl.settings import download_progress_bar_resolution, download_chunk_size, token_queue_refresh_rate, status_time, num_tries_download, sleep_time_for_isis, download_timeout, status_chop_off, \
    download_timeout_multiplier, token_queue_download_refresh_rate, status_progress_bar_resolution

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer


class Dummy:
    def set_status(self, _: Any) -> None:
        return


class SessionWithKey(Session):
    def __init__(self, key: str, token: str):
        super().__init__()
        self.key = key
        self.token = token

    @classmethod
    def from_scratch(cls, user: User, status: Union[InfoStatus, Dummy] = Dummy()) -> Optional[SessionWithKey]:
        s = cls("", "")
        s.headers.update({"User-Agent": "isisdl (Python Requests)"})

        status.set_status(PreStatusInfo.authenticating0)
        s.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")

        status.set_status(PreStatusInfo.authenticating1)
        s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s1",
               data={
                   "shib_idp_ls_exception.shib_idp_session_ss": "",
                   "shib_idp_ls_success.shib_idp_session_ss": "false",
                   "shib_idp_ls_value.shib_idp_session_ss": "",
                   "shib_idp_ls_exception.shib_idp_persistent_ss": "",
                   "shib_idp_ls_success.shib_idp_persistent_ss": "false",
                   "shib_idp_ls_value.shib_idp_persistent_ss": "",
                   "shib_idp_ls_supported": "", "_eventId_proceed": "",
               })

        status.set_status(PreStatusInfo.authenticating3)
        response = s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
                          params={"j_username": user.username, "j_password": user.password, "_eventId_proceed": ""})

        status.set_status(PreStatusInfo.authenticating4)

        if response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            # The redirection did not work → credentials are wrong
            return None

        # Extract the session key
        key = response.text.split("https://isis.tu-berlin.de/login/logout.php?sesskey=")[-1].split("\"")[0]

        try:
            # This is a somewhat dirty hack.
            # In order to obtain a token one usually calls the `login/token.php` site.
            # ISIS handles authentication via SSO, which leads to an invalid password every time.

            # In [1] this way of obtaining the token is described.
            # I would love to get a better way working, but unfortunately it seems as if it is not supported.
            #
            # [1]: https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Obtain-a-Token#get-a-token-with-sso-login

            s.get("https://isis.tu-berlin.de/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledownloader")
            raise InvalidSchema
        except InvalidSchema as ex:
            token = standard_b64decode(str(ex).split("token=")[-1]).decode().split(":::")[1]

        s.key = key
        s.token = token

        return s

    @staticmethod
    def _timeouter(func: Any, *args: Iterable[Any], **kwargs: Dict[Any, Any]) -> Any:
        i = 0
        while i < num_tries_download:
            try:
                return func(*args, timeout=download_timeout + download_timeout_multiplier ** (0.5 * i), **kwargs)

            except Exception:
                # Later: Server
                time.sleep(sleep_time_for_isis)
                i += 1

    def get_(self, *args: Any, **kwargs: Any) -> Optional[Response]:
        return cast(Optional[Response], self._timeouter(super().get, *args, **kwargs))

    def post_(self, *args: Any, **kwargs: Any) -> Optional[Response]:
        return cast(Optional[Response], self._timeouter(super().post, *args, **kwargs))

    def head_(self, *args: Any, **kwargs: Any) -> Optional[Response]:
        return cast(Optional[Response], self._timeouter(super().head, *args, **kwargs))

    def __str__(self) -> str:
        return "~Session~"

    def __repr__(self) -> str:
        return "~Session~"


# Represents a granted token. A download may only download as much as defined in num_bytes.
@dataclass
class Token:
    num_bytes: int = download_chunk_size


class DownloadThrottler(Thread):
    """
    This class acts in a way that the download speed is capped at a certain maximum.
    It does so by handing out tokens, which are limited.
    With every token you may download a chunk of size `download_chunk_size`.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.active_tokens: Queue[Token] = Queue()
        self.used_tokens: Queue[Token] = Queue()
        self.timestamps_tokens: List[float] = []

        self.download_rate = args.download_rate or config.throttle_rate or -1

        for _ in range(self.max_tokens()):
            self.active_tokens.put(Token())

        # Dummy token used to maybe return it all the time.
        self.token = Token()

        self.start()

    def run(self) -> None:
        # num has to be distributed over `token_queue_refresh_rate` seconds. We're inserting them all at the beginning.
        num = self.max_tokens()

        while True:
            # Clear old timestamps
            start = time.perf_counter()
            while self.timestamps_tokens:
                if self.timestamps_tokens[0] < start - token_queue_download_refresh_rate:
                    self.timestamps_tokens.pop(0)
                else:
                    break

            if self.download_rate is not None:
                # If a download limit is imposed hand out new tokens
                try:
                    for _ in range(num):
                        self.active_tokens.put(self.used_tokens.get(block=False))

                except (Full, Empty):
                    pass

            # Finally, compute how much time we've spent doing this stuff and sleep the remainder.
            time.sleep(max(token_queue_refresh_rate - (time.perf_counter() - start), 0))

    @property
    def bandwidth_used(self) -> float:
        """
        Return the bandwidth used in bytes / second
        """
        return len(self.timestamps_tokens) * download_chunk_size / token_queue_download_refresh_rate

    def get(self) -> Token:
        try:
            if self.download_rate == -1:
                return self.token

            token = self.active_tokens.get()
            self.used_tokens.put(token)

            return token

        finally:
            # Only append it at exit
            self.timestamps_tokens.append(time.perf_counter())

    def max_tokens(self) -> int:
        if self.download_rate == -1:
            return 1

        return int(self.download_rate * 1024 ** 2 // download_chunk_size * token_queue_refresh_rate)


# This is kinda bloated. Maybe I'll remove it in the future.
class MediaType(enum.Enum):
    video = enum.auto()
    document = enum.auto()

    @property
    def dir_name(self) -> str:
        if self == MediaType.video:
            return "Videos"

        return ""

    @staticmethod
    def list_dirs() -> Iterable[str]:
        return "Videos",


@dataclass
class MediaContainer:
    name: str
    url: str
    location: str
    media_type: MediaType
    s: SessionWithKey
    container: PreMediaContainer
    size: int = -1
    curr_size: int = 0
    _exit: bool = False
    done: bool = False
    tot_time = 0

    @staticmethod
    def from_pre_container(container: PreMediaContainer, s: SessionWithKey) -> Optional[MediaContainer]:
        if not args.overwrite:
            other_size = database_helper.get_size_from_file_id(container.file_id)
            if container.size == other_size:
                return None

        media_type = MediaType.video if container.is_video else MediaType.document
        return MediaContainer(container._name, container.url, container.path, media_type, s, container, container.size)

    def download(self, throttler: DownloadThrottler) -> None:
        if self._exit:
            self.done = True
            return

        running_download = self.s.get_(self.url, params={"token": self.s.token}, stream=True)

        if running_download is None or not running_download.ok:
            self.done = True
            return

        if self.size == -1:
            try:
                self.size = int(running_download.headers["content-length"])
            except KeyError:
                pass

        with open(self.location, "wb") as f:
            # We copy in chunks to add the rate limiter and status indicator. This could also be done with `shutil.copyfileobj`.
            # Also remember to set the `decode_content=True` kwarg in `.read()`.
            while True:
                token = throttler.get()

                i = 0
                while i < num_tries_download:
                    try:
                        new = running_download.raw.read(token.num_bytes, decode_content=True)
                        break

                    except Exception:
                        i += 1

                if len(new) == 0:
                    # No file left
                    break

                f.write(new)
                self.curr_size += len(new)

            f.flush()

        running_download.close()

        # Only register the file after successfully downloading it.
        self.container.checksum = calculate_local_checksum(Path(self.location))
        self.container.dump()
        self.done = True

        return None

    def stop(self) -> None:
        self._exit = True

    @property
    def percent_done(self) -> str:
        if self.size in {0, -1}:
            percent: float = 0
        else:
            percent = self.curr_size / self.size

        # Sometimes this bug happens… I don't know why
        if percent > 1:
            percent = 1

        progress_chars = int(percent * download_progress_bar_resolution)
        return "╶" + "█" * progress_chars + " " * (download_progress_bar_resolution - progress_chars) + "╴"

    def __hash__(self) -> int:
        # The url is known and unique. No need to store an extra field "checksum".
        return self.url.__hash__()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.name


class DownloadStatus(Thread):
    def __init__(self, files: List[MediaContainer], num_threads: int, throttler: DownloadThrottler) -> None:
        self._shutdown = False
        self.finished_files = 0
        self.total_files = len(files)
        self.total_size = sum(item.size for item in files if item.size != -1)
        self.total_downloaded = 0
        self.last_text_len = 0
        self.throttler = throttler

        self.thread_files: Dict[int, Optional[MediaContainer]] = {i: None for i in range(num_threads)}
        super().__init__(daemon=True)

    def add(self, thread_id: int, container: MediaContainer) -> None:
        self.thread_files[thread_id] = container

    def finish(self, thread_id: int) -> None:
        item = self.thread_files[thread_id]
        self.thread_files[thread_id] = None

        if item is None:
            return

        self.total_downloaded += item.curr_size
        self.finished_files += 1

    def shutdown(self) -> None:
        self._shutdown = True

    def run(self) -> None:
        while True:
            time.sleep(status_time)
            if all(item is None for item in self.thread_files.values()):
                continue

            log_strings: List[str] = []

            def format_num(num: float) -> str:
                # Yes, checking float with `==` is "bad" - but it is passed as an integer in this case.
                if num == -1:
                    return "  ...     "

                a, b = HumanBytes.format(num)
                return f"{a: >6.2f} {b}"

            def format_quick(num: float) -> str:
                a, b = HumanBytes.format(num)
                return f"{a:.2f} {b}"

            curr_bandwidth = format_quick(self.throttler.bandwidth_used)
            downloaded_bytes = self.total_downloaded + sum(item.curr_size for item in self.thread_files.values() if item is not None)
            total_size = format_quick(self.total_size)

            # General meta-info
            log_strings.append("")
            log_strings.append(f"Current bandwidth usage: {curr_bandwidth}/s")
            log_strings.append(f"Downloaded {format_quick(downloaded_bytes)} / {total_size}")
            log_strings.append(f"Finished:  {self.finished_files} / {self.total_files} files")
            log_strings.append(f"ETA: {datetime.timedelta(seconds=int((self.total_size - downloaded_bytes) / max(self.throttler.bandwidth_used, 1)))}")
            log_strings.append("")

            # Now determine the already downloaded amount and display it
            thread_format = math.ceil(math.log10(len(self.thread_files) or 1))
            for thread_id, container in self.thread_files.items():
                thread_string = f"Thread {thread_id:{' '}<{thread_format}}"
                if container is None:
                    log_strings.append(thread_string)
                    continue

                curr_size = format_num(container.curr_size)
                max_size = format_num(container.size)

                log_strings.append(f"{thread_string} {container.percent_done} [ {curr_size} | {max_size} ] - {container.name}")
                pass

            if self._shutdown:
                log_strings.extend(["", "Please wait for the downloads to finish ..."])

            self.last_text_len = print_log_messages(log_strings, self.last_text_len)


class PreStatusInfo(enum.Enum):
    startup = 0
    authenticating0 = 5
    authenticating1 = 10
    authenticating2 = 20
    authenticating3 = 25
    authenticating4 = 30

    content: Any = []
    get_content = 70

    done = 100


class InfoStatus(Thread):
    def __init__(self) -> None:
        self._running = True
        self.last_text_len = 0
        self.status = PreStatusInfo.startup
        self.i = 0
        self.max_content = 0

        super().__init__(daemon=True)

    def set_status(self, status: PreStatusInfo) -> None:
        self.status = status
        self.i = 0

    def set_max_content(self, num: int) -> None:
        self.max_content = num

    def run(self) -> None:
        video_cache_exists = database_helper.get_video_cache_exists()
        while self._running:
            time.sleep(status_time)

            log_strings = []

            if self.status == PreStatusInfo.startup:
                message = "Starting up"

            elif self.status.name.startswith("authenticating"):
                message = "Authenticating with ISIS"

            elif self.status == PreStatusInfo.content:
                message = "Getting the content of the Courses"

            else:
                message = ""

            log_strings.append("")
            log_strings.append(f"{message} {'.' * self.i}")

            if not video_cache_exists and self.status == PreStatusInfo.content and not (args.disable_videos or not config.download_videos):
                log_strings.append("(This may take a while for the first time)")

            log_strings.append("")

            if isinstance(self.status.value, int):
                perc_done = int(self.status.value / PreStatusInfo.done.value * status_progress_bar_resolution)

            elif isinstance(self.status.value, list):
                assert self.max_content > 0
                threads_finished_perc = PreStatusInfo.get_content.value * len(self.status.value) / self.max_content
                perc_done = int((PreStatusInfo.authenticating4.value + threads_finished_perc) / PreStatusInfo.done.value * status_progress_bar_resolution)

            else:
                perc_done = 0

            log_strings.append(f"[{'█' * perc_done}{' ' * (status_progress_bar_resolution - perc_done)}]")

            if self._running:
                self.last_text_len = print_log_messages(log_strings, self.last_text_len)

            self.i = (self.i + 1) % 4

    def stop(self) -> None:
        self._running = False


def maybe_chop_off_str(st: str, width: int) -> str:
    if len(st) > width - status_chop_off + 1:
        return st[:width - status_chop_off] + "." * status_chop_off
    return st.ljust(width)


def print_log_messages(strings: List[str], last_num: int) -> int:
    if last_num:
        print(f"\033[{last_num}F", end="")

    # First sanitize the output
    width = shutil.get_terminal_size().columns

    for i, item in enumerate(strings):
        strings[i] = maybe_chop_off_str(item, width)

    final_str = "\n".join(strings)
    print(final_str)

    # Erase all previous chars
    return final_str.count("\n") + 1
