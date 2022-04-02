"""
This file is concerned with how to download an actual file given an url.
"""

from __future__ import annotations

import datetime
import enum
import os
import shutil
import time
from base64 import standard_b64decode
from dataclasses import dataclass
from pathlib import Path
from queue import Full, Queue, Empty
from threading import Thread
from typing import Optional, List, Any, Iterable, Dict, TYPE_CHECKING, cast

import math
from requests import Session, Response
from requests.exceptions import InvalidSchema

from isisdl.backend.utils import HumanBytes, args, User, calculate_local_checksum, database_helper, config, clear, error_text
from isisdl.settings import download_progress_bar_resolution, download_chunk_size, status_time, num_tries_download, sleep_time_for_isis, download_timeout, status_chop_off, \
    download_timeout_multiplier, token_queue_download_refresh_rate, status_progress_bar_resolution, is_windows, external_links_num_slow, throttler_low_prio_sleep_time, token_queue_refresh_rate

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer

# Use the variable to do nothing such that the type checker doesn't complain.
token_queue_refresh_rate


class Dummy:
    def set_status(self, _: Any) -> None:
        return


class SessionWithKey(Session):
    def __init__(self, key: str, token: str):
        super().__init__()
        self.key = key
        self.token = token

    @classmethod
    def from_scratch(cls, user: User) -> Optional[SessionWithKey]:
        try:
            s = cls("", "")
            s.headers.update({"User-Agent": "isisdl (Python Requests)"})

            s.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")
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

            response = s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
                              params={"j_username": user.username, "j_password": user.password, "_eventId_proceed": ""})

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
        except Exception as ex:
            print(f"{error_text} I was unable to establish a connection.\n\nReason: {ex}\n\nBailing out!")
            os._exit(1)

    @staticmethod
    def _timeouter(func: Any, *args: Iterable[Any], **kwargs: Dict[Any, Any]) -> Any:
        if "tubcloud.tu-berlin.de" in args[0]:
            # The tubcloud is *really* slow
            _download_timeout = 20
        else:
            _download_timeout = download_timeout

        i = 0
        while i < num_tries_download:
            try:
                return func(*args, timeout=_download_timeout + download_timeout_multiplier ** (0.5 * i), **kwargs)

            except Exception:
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


# TODO: Refactor into 2 queues, 1 streaming, 1 downloading.
class DownloadThrottler(Thread):
    """
    This class acts in a way that the download speed is capped at a certain maximum.
    It does so by handing out tokens, which are limited.
    With every token you may download a chunk of size `download_chunk_size`.
    """

    def __init__(self) -> None:
        self.active_tokens: Queue[Token] = Queue()
        self.used_tokens: Queue[Token] = Queue()
        self.timestamps_tokens: List[float] = []
        self._streaming_loc: Optional[str] = None

        self.download_rate = args.download_rate or config.throttle_rate or -1

        # Maybe the token_queue_refresh_rate is too small and there will be no tokens.
        # Check if that will be the case and adapt it accordingly.

        global token_queue_refresh_rate
        if self.download_rate != -1:
            while self.max_tokens() < args.num_threads:
                token_queue_refresh_rate *= 2

        for _ in range(self.max_tokens()):
            self.active_tokens.put(Token())

        # Dummy token used to maybe return it all the time.
        self.token = Token()

        super().__init__(daemon=True)
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
        Returns the bandwidth used in bytes / second
        """
        return len(self.timestamps_tokens) * download_chunk_size / token_queue_download_refresh_rate

    def get(self, location: str) -> Token:
        while self._streaming_loc is not None and location != self._streaming_loc:
            time.sleep(throttler_low_prio_sleep_time)

        if self.download_rate == -1:
            return self.token

        token = self.active_tokens.get()
        self.used_tokens.put(token)

        self.timestamps_tokens.append(time.perf_counter())
        return token

    def start_stream(self, location: str) -> None:
        self._streaming_loc = location

    def end_stream(self) -> None:
        self._streaming_loc = None

    def max_tokens(self, refresh_rate: Optional[float] = None) -> int:
        if self.download_rate == -1:
            return 1

        return int(self.download_rate * 1024 ** 2 // download_chunk_size * (refresh_rate or token_queue_refresh_rate)) or 1


# This is kinda bloated. Maybe I'll remove it in the future.
class MediaType(enum.Enum):
    video = 1
    document = 2
    extern = 3

    @property
    def dir_name(self) -> str:
        if self == MediaType.video:
            return "Videos"
        if self == MediaType.extern:
            return "Extern"

        return ""

    @staticmethod
    def list_dirs() -> Iterable[str]:
        return "Videos", "Extern"


# TODO: Is this class even necessary?
@dataclass
class MediaContainer:
    name: str
    url: str
    location: str
    media_type: MediaType
    s: SessionWithKey
    container: PreMediaContainer
    size: int = -1
    curr_size: Optional[int] = None
    _exit: bool = False
    done: bool = False
    tot_time = 0

    @staticmethod
    def from_pre_container(container: PreMediaContainer, s: SessionWithKey) -> Optional[MediaContainer]:
        other_size = database_helper.get_size_from_url(container.url)
        if container.size == other_size and database_helper.get_checksum_from_url(container.url) is not None:
            return None

        return MediaContainer(container._name, container.download_url, container.path, container.media_type, s, container, container.size)

    def download(self, throttler: DownloadThrottler, is_stream: bool = False) -> None:
        if self._exit or self.done:
            self.done = True
            return

        self.curr_size = 0

        if is_stream:
            throttler.start_stream(self.location)

        running_download = self.s.get_(self.url, params={"token": self.s.token}, stream=True)

        if running_download is not None and running_download.status_code == 451:
            database_helper.add_bad_url(self.url)

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
                # if self._exit:
                #     return

                token = throttler.get(self.location)

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

        if is_stream:
            throttler.end_stream()

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
        elif self.curr_size is None:
            percent = 0
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


# TODO: ETA down when stopping the download (should be done)
# TODO: When already done file add them in the beginning instead of subtracting: 0 / 300 → 200 / 500
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
        self.stream_file: Optional[MediaContainer] = None
        super().__init__(daemon=True)

    def add(self, thread_id: int, container: MediaContainer) -> None:
        self.thread_files[thread_id] = container

    def add_streaming_file(self, container: MediaContainer) -> None:
        self.stream_file = container

    def done_streaming_file(self) -> None:
        self.stream_file = None

    def finish(self, thread_id: int) -> None:
        item = self.thread_files[thread_id]
        self.thread_files[thread_id] = None

        if item is None:
            return

        self.finished_files += 1
        if item.curr_size is not None:
            self.total_downloaded += item.curr_size
        elif item._exit:
            self.total_downloaded += item.size

    def shutdown(self) -> None:
        self._shutdown = True

    def run(self) -> None:
        while True:
            time.sleep(status_time)
            # if all(item is None for item in self.thread_files.values()):
            #     continue

            log_strings: List[str] = []

            curr_bandwidth = HumanBytes.format_str(self.throttler.bandwidth_used)

            downloaded_bytes = self.total_downloaded + sum(item.curr_size for item in self.thread_files.values() if item is not None and item.curr_size is not None)
            total_size = HumanBytes.format_str(self.total_size)

            # TODO: Reorder status for location / name display
            log_strings.append("")
            log_strings.append(f"Current bandwidth usage: {curr_bandwidth}/s {'(throttled)' if self.throttler.download_rate != -1 else ''}")

            if args.stream:
                log_strings.append("")
                if self.stream_file is not None:
                    log_strings.append(f"Stream: {self.stream_file.percent_done} "
                                       f"[ {HumanBytes.format_pad(self.stream_file.curr_size)} | {HumanBytes.format_pad(self.stream_file.size)} ]"
                                       f" - {self.stream_file.location}")
                else:
                    log_strings.append("Stream: Waiting")
            else:
                # General meta-info
                log_strings.append(f"Downloaded {HumanBytes.format_str(downloaded_bytes)} / {total_size}")
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

                    log_strings.append(f"{thread_string} {container.percent_done} [ {HumanBytes.format_pad(container.curr_size)} | {HumanBytes.format_pad(container.size)} ] - {container.location}")
                    pass

                # Optional streaming info
                if self.stream_file is not None:
                    log_strings.append("")
                    log_strings.append(
                        f"Stream:  {self.stream_file.percent_done} [ {HumanBytes.format_pad(self.stream_file.curr_size)} | {HumanBytes.format_pad(self.stream_file.size)} ]"
                        f" - {self.stream_file.location}")
                else:
                    log_strings.extend(["", ""])

            if self._shutdown:
                log_strings.extend(["", "Please wait for the downloads to finish ..."])

            self.last_text_len = print_log_messages(log_strings, self.last_text_len)


class PreStatusInfo(enum.Enum):
    startup = 0
    authenticating = 1
    getting_content = 2
    getting_extern = 3
    done = 4


# TODO: When sync-ing after lot of deleting the progress bar becomes large.
class InfoStatus(Thread):
    def __init__(self) -> None:
        self._running = True
        self.status = PreStatusInfo.startup

        self.last_text_len = 0
        self.i = 0
        self.max_content: Optional[int] = None
        self.done = 0

        super().__init__(daemon=True)

    def set_status(self, status: PreStatusInfo) -> None:
        self.status = status
        self.max_content = None
        self.done = 0
        self.i = 0

    def set_max_content(self, num: int) -> None:
        self.max_content = num

    def done_thing(self) -> None:
        self.done += 1

    def run(self) -> None:
        from isisdl.backend.request_helper import external_links, PreMediaContainer

        while self._running:
            time.sleep(status_time)
            log_strings = []

            if self.status == PreStatusInfo.startup:
                message = "Starting up"

            elif self.status == PreStatusInfo.authenticating:
                message = "Authenticating with ISIS"

            elif self.status == PreStatusInfo.getting_content:
                message = "Getting the content of the Courses"

            elif self.status == PreStatusInfo.getting_extern:
                # TODO: This is not accurate
                message = "Sending webrequests to external websites for additional content"

            else:
                message = ""

            log_strings.append("")
            log_strings.append(f"{message} {'.' * self.i}")

            if self.status == PreStatusInfo.getting_extern and len(external_links) > external_links_num_slow:
                video_done, video_total = 0, 0
                extern_done, extern_total = 0, 0

                for link in external_links:
                    if link.media_type == MediaType.video:
                        video_total += 1
                        if PreMediaContainer.from_dump(link.url) is not None:
                            video_done += 1

                    elif link.media_type == MediaType.extern:
                        extern_total += 1
                        if PreMediaContainer.from_dump(link.url) is not None:
                            extern_done += 1

                log_strings.append(f"({video_done:>{int(math.log10(video_total or 1)) + 1}} / {video_total} videos, "
                                   f"{extern_done:>{int(math.log10(extern_total or 1))}} / {extern_total} external links, will be cached)")

            log_strings.append("")
            if self.max_content is not None:
                perc_done = int(self.done / self.max_content * status_progress_bar_resolution)
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
        if is_windows:
            # Windows does not support ANSI escape sequences…
            clear()
        else:
            print(f"\033[{last_num}F", end="")

    # First sanitize the output
    width = shutil.get_terminal_size().columns

    for i, item in enumerate(strings):
        strings[i] = maybe_chop_off_str(item, width)

    final_str = "\n".join(strings)
    print(final_str)

    # Erase all previous chars
    return final_str.count("\n") + 1
