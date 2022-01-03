"""
This file is concerned with how to download an actual file given an url.
"""
from __future__ import annotations

import enum
import math
import os
import shutil
import time
from base64 import standard_b64decode
from dataclasses import dataclass
from datetime import datetime
from queue import Full, Queue, Empty
from threading import Thread
from typing import Optional, List, Any, Iterable, Dict, Tuple, Union, TYPE_CHECKING, cast, Set

import requests
from bs4 import BeautifulSoup
from func_timeout import FunctionTimedOut, func_timeout
from requests import Session, Response
from requests.exceptions import InvalidSchema

from isisdl.share.settings import progress_bar_resolution, download_chunk_size, token_queue_refresh_rate, status_time, num_tries_download, sleep_time_for_isis, download_timeout, status_chop_off, \
    download_timeout_multiplier, token_queue_download_refresh_rate
from isisdl.share.utils import HumanBytes, args, logger, e_format, User, calculate_checksum, database_helper

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer


class SessionWithKey(Session):
    def __init__(self, key: str, token: str):
        super().__init__()
        self.key = key
        self.token = token

    @classmethod
    def from_scratch(cls, user: User, num: int) -> SessionWithKey:
        s = cls("", "")
        s.headers.update({"User-Agent": "UwU"})

        s.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")

        s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s1",
               data={"shib_idp_ls_exception.shib_idp_session_ss": "", "shib_idp_ls_success.shib_idp_session_ss": "false", "shib_idp_ls_value.shib_idp_session_ss": "",
                     "shib_idp_ls_exception.shib_idp_persistent_ss": "", "shib_idp_ls_success.shib_idp_persistent_ss": "false", "shib_idp_ls_value.shib_idp_persistent_ss": "",
                     "shib_idp_ls_supported": "", "_eventId_proceed": "", })

        response = s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
                          params={"j_username": user.username, "j_password": user.password, "_eventId_proceed": ""})

        if response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            # The redirection did not work → credentials are wrong
            logger.error(f"I had a problem getting the {user = !s}. You have probably entered the wrong credentials.\nBailing out…")
            os._exit(69)

        if num == 0:
            logger.info(f"Credentials for {user} accepted!")

        # Extract the session key
        soup = BeautifulSoup(response.text, features="html.parser")
        key = soup.find("input", {"name": "sesskey"})["value"]

        try:
            # This is a somewhat dirty hack.
            # In order to obtain a token one usually calls the `login/token.php` site, however since ISIS handles authentication via SSO, this always results in an invalid password.
            # In https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Obtain-a-Token#get-a-token-with-sso-login this way of obtaining the token is described.
            # I would love to get a better way working, but unfortunately it seems as if it is not supported.
            s.get("https://isis.tu-berlin.de/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledownloader")
            raise InvalidSchema
        except InvalidSchema as ex:
            token = standard_b64decode(str(ex).split("token=")[-1]).decode().split(":::")[1]

        s.key = key
        s.token = token

        return s

    @staticmethod
    def _timeouter(func, *args: Iterable[Any], extra_timeout, **kwargs: Dict[Any, Any]) -> Any:  # type: ignore
        i = 0
        while i < num_tries_download:
            try:
                return func_timeout(download_timeout + extra_timeout + download_timeout_multiplier ** (0.5 * i), func, args, kwargs)

            except FunctionTimedOut:
                logger.debug(f"Timed out getting url ({i} / {num_tries_download - 1}) {args[0]}")
                # logger.debug("".join(traceback.format_stack()))
                i += 1

            except requests.exceptions.ConnectionError:
                logger.warning(f"ISIS is complaining about the number of downloads (I am ignoring it). Consider dropping the thread count. Sleeping for {sleep_time_for_isis}s")
                time.sleep(sleep_time_for_isis)
                i += 1

    def get_(self, *args, extra_timeout=0, **kwargs) -> Optional[Response]:  # type: ignore
        return cast(Optional[Response], self._timeouter(super().get, *args, extra_timeout=extra_timeout, **kwargs))

    def post_(self, *args, extra_timeout=0, **kwargs) -> Optional[Response]:  # type: ignore
        return cast(Optional[Response], self._timeouter(super().post, *args, extra_timeout=extra_timeout, **kwargs))

    def head_(self, *args, extra_timeout=0, **kwargs) -> Optional[Response]:  # type: ignore
        return cast(Optional[Response], self._timeouter(super().head, *args, extra_timeout=extra_timeout, **kwargs))

    def text(self, *args, extra_timeout=0, **kwargs) -> Optional[str]:  # type: ignore
        res = self.get_(*args, extra_timeout=extra_timeout, **kwargs)
        if res is None:
            return None

        if res.ok:
            return res.text

        return None

    def __str__(self) -> str:
        return f"Session with key={self.key}"

    def __repr__(self) -> str:
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

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.active_tokens: Queue[Token] = Queue()
        self.used_tokens: Queue[Token] = Queue()
        self.timestamps_tokens: List[float] = []

        for _ in range(self.max_tokens()):
            self.active_tokens.put(Token())

        # Dummy token used to maybe return it all the time.
        self.token = Token()

        self.start()

    def run(self) -> None:
        # num has to be distributed over `token_queue_refresh_rate` seconds. We're inserting them all at the beginning.
        num = DownloadThrottler.max_tokens()

        while True:
            # Clear old timestamps
            start = time.perf_counter()
            while self.timestamps_tokens:
                if self.timestamps_tokens[0] < start - token_queue_download_refresh_rate:
                    self.timestamps_tokens.pop(0)
                else:
                    break

            if hasattr(args, "download_rate") and args.download_rate is not None:
                # If a download limit is imposed hand out new tokens
                try:
                    for _ in range(num):
                        self.active_tokens.put(self.used_tokens.get())

                except (Full, Empty):
                    pass

            time.sleep(max(token_queue_refresh_rate - (time.perf_counter() - start), 0))

    @property
    def bandwidth_used(self) -> float:
        """
        Return the bandwidth used in bytes / second
        """
        return len(self.timestamps_tokens) * download_chunk_size / token_queue_download_refresh_rate

    def get(self) -> Token:
        try:
            if args.download_rate is None:
                return self.token

            token = self.active_tokens.get()
            self.used_tokens.put(token)

            return token

        finally:
            # Only append it at exit
            self.timestamps_tokens.append(time.perf_counter())

    @staticmethod
    def max_tokens() -> int:
        if not hasattr(args, "download_rate") or args.download_rate is None:
            return 1

        return int(args.download_rate * 1024 ** 2 // download_chunk_size * token_queue_refresh_rate)


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
            other_timestamp = database_helper.get_time_from_file_id(container.file_id)
            if other_timestamp is not None:
                # Entry was found → skip if newer or equal to the file.
                other_time = datetime.fromtimestamp(other_timestamp)

                if other_time <= container.time:
                    return None

                if other_time != container.time:
                    logger.warning(f"Different times: {other_time = }, {container.time = }")

        media_type = MediaType.video if container.is_video else MediaType.document
        location = os.path.join(container.location, container.name)

        return MediaContainer(container.name, container.url, location, media_type, s, container)

    def download(self) -> None:
        if self._exit:
            status.stop_request_download(self)
            self.done = True
            return

        running_download = self.s.get_(self.url, params={"token": self.s.token}, stream=True)

        if running_download is None or not running_download.ok:
            status.timeout_exit_download(self)
            self.done = True
            return

        try:
            self.size = int(running_download.headers["content-length"])
        except KeyError:
            pass

        status.start_download(self)

        with open(self.location, "wb") as f:
            # We copy in chunks to add the rate limiter and status indicator. This could also be done with `shutil.copyfileobj`.
            while True:
                token = throttler.get()

                new = running_download.raw.read(token.num_bytes)
                if len(new) == 0:
                    # No file left
                    break

                f.write(new)
                self.curr_size += len(new)

            f.flush()

        running_download.close()

        # Only register the file after successfully downloading it.
        self.container.checksum = calculate_checksum(self.location)
        self.container.dump()
        self.done = True
        status.normal_exit_download(self)

        return None

    def stop(self) -> None:
        self._exit = True

    @property
    def percent_done(self) -> float:
        return self.curr_size / self.size

    @property
    def progress_bar(self) -> str:
        progress = int(self.percent_done * progress_bar_resolution)
        return "╶" + "█" * progress + " " * (progress_bar_resolution - progress) + "╴"

    def __hash__(self) -> int:
        # The url is known and unique. No need to store an extra field "checksum".
        return self.url.__hash__()

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return self.name

    def error_format(self) -> str:
        lf = "\n" + " " * 8
        return self.name + ":" + lf + "Name:     " + self.name + lf + "Course:   " + self.container.course_name + lf + "Url:      " + self.url


class Status(Thread):
    _shutdown_requested = False
    num_files = 0
    last_len = 0
    status_file_mapping: Dict[str, Set[MediaContainer]] = {
        "not_started": set(),
        "downloading": set(),
        "succeeded": set(),
        "timeout": set(),
        "stopped": set(),
    }

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.start()

    @staticmethod
    def add_files(files: List[MediaContainer]) -> None:
        Status.status_file_mapping["not_started"].update(files)
        Status.num_files += len(files)
        # If the status indicator is running disable all logging
        logger.disabled = True

    @staticmethod
    def _move_from_to(file: MediaContainer, src: str, dest: str) -> None:
        Status.status_file_mapping[src].remove(file)
        Status.status_file_mapping[dest].add(file)

    @staticmethod
    def start_download(file: MediaContainer) -> None:
        Status._move_from_to(file, "not_started", "downloading")

    @staticmethod
    def normal_exit_download(file: MediaContainer) -> None:
        Status._move_from_to(file, "downloading", "succeeded")

    @staticmethod
    def timeout_exit_download(file: MediaContainer) -> None:
        Status._move_from_to(file, "downloading", "timeout")

    @staticmethod
    def stop_request_download(file: MediaContainer) -> None:
        Status._move_from_to(file, "not_started", "stopped")

    @staticmethod
    def total_downloaded() -> int:
        all_items: Set[MediaContainer] = {item for row in Status.status_file_mapping.values() for item in row}
        return sum(item.curr_size for item in all_items)

    @staticmethod
    def request_shutdown() -> None:
        Status._shutdown_requested = True

    def run(self) -> None:
        Status.last_len = 0
        while True:
            time.sleep(status_time)
            to_download = {item for name, queue in Status.status_file_mapping.items() for item in queue if name != "succeeded" and name != "stopped"}
            if not to_download:
                if Status._shutdown_requested:
                    break
                continue

            # Start off by erasing all previous chars
            log_strings: List[str] = []

            def format_int(num: int) -> str:
                # log_10(num) = number of numbers
                return f"{num:{' '}>{math.ceil(math.log10(Status.num_files or 1))}}"

            def format_lst(lst: Set[Any]) -> str:
                return format_int(len(lst)) + " " * (len(format_int(Status.num_files)) + 3)

            def format_num(num: float) -> str:
                a, b = HumanBytes.format(num)
                return f"{a:.2f} {b}"

            first_str = ""
            if Status.last_len:
                first_str += f"\033[{Status.last_len}A\r"

            first_str += " -- Status --"
            log_strings.append(first_str)
            curr_download = format_num(throttler.bandwidth_used)
            log_strings.append(f"Current bandwidth usage: {curr_download}/s    ")

            downloaded_bytes = format_num(sum(item.curr_size for queue in self.status_file_mapping.values() for item in queue))
            log_strings.append(f"Downloaded {downloaded_bytes}        ")
            log_strings.append(f"Finished: {format_int(len(Status.status_file_mapping['succeeded']))} / {format_int(Status.num_files)} files")
            log_strings.append(f"Skipped:  {format_lst(Status.status_file_mapping['stopped'])} files (Exit)")
            log_strings.append(f"Skipped:  {format_lst(Status.status_file_mapping['timeout'])} files (Timeout)")

            # Now determine the the already downloaded amount and display it
            downloading = Status.status_file_mapping["downloading"]
            curr_download_strings: List[str] = []
            if downloading:
                done: List[Tuple[Union[int, float], str]] = [HumanBytes.format(num.curr_size) for num in downloading]
                first = e_format([num[0] for num in done])
                first_units = [item[1] for item in done]

                max_values: List[Tuple[Union[int, float], str]] = [HumanBytes.format(num.size) for num in downloading]
                second = e_format([num[0] for num in max_values])
                second_units = [item[1] if item[0] is not None else '   ' for item in max_values]

                progress_str = [item.progress_bar for item in downloading]

                # Use a tuple to sort based on percent done.
                final_middle = [
                    (container.percent_done or 0, f"{progress} [{already} {already_unit} / {size} {size_unit}] - {container.name}")

                    for container, already, already_unit, size, size_unit, progress in
                    zip(downloading, first, first_units, second, second_units, progress_str)
                ]

                curr_download_strings.extend(item[1] for item in sorted(final_middle, key=lambda x: x[0], reverse=True))

            # Now sanitize the output
            width = shutil.get_terminal_size().columns

            new_log_strings = []

            def maybe_chop_off(item: str) -> str:
                if len(item) > width - status_chop_off + 1:
                    return item[:width - status_chop_off] + "." * status_chop_off
                return item.ljust(width)

            for item in log_strings:
                new_log_strings.append(maybe_chop_off(item))

            if Status._shutdown_requested:
                new_log_strings.append(maybe_chop_off("\nPlease wait for shutdown…"))

            new_log_strings.append(maybe_chop_off(""))
            for item in curr_download_strings:
                item = maybe_chop_off(item)
                new_log_strings.append(item)

            pre_final_string = "\n".join(new_log_strings)
            new_log_strings.extend([" " * width for _ in range(max(0, Status.last_len - pre_final_string.count("\n") - 1))])

            final_str = "\n".join(new_log_strings)
            Status.last_len = final_str.count("\n") + 1

            print(final_str)

        logger.disabled = False


status = Status()
throttler = DownloadThrottler()
