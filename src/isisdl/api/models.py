from __future__ import annotations

import os.path
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Type, TypedDict, TYPE_CHECKING

from aiohttp import ClientSession as InternetSession
from aiohttp.client import _RequestContextManager, ClientTimeout
from sqlalchemy import Text, Enum as SQLEnum, ForeignKey, String, Integer, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from isisdl.db_conf import DataBase
from isisdl.settings import download_base_timeout, download_timeout_multiplier, num_tries_download, download_static_sleep_time, working_dir_location, temp_file_location, checksum_algorithm, logger
from isisdl.utils import sanitize_path

if TYPE_CHECKING:
    from isisdl.backend.models import Config


class Course(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)

    preferred_name: Mapped[str | None] = mapped_column(Text, nullable=True)  # TODO: When merging, does the null update also get merged?
    short_name: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)

    number_users: Mapped[int] = mapped_column(nullable=False)
    is_favorite: Mapped[bool] = mapped_column(nullable=False)

    time_of_last_access: Mapped[datetime | None] = mapped_column(nullable=True)
    time_of_last_modification: Mapped[datetime | None] = mapped_column(nullable=True)
    time_of_start: Mapped[datetime | None] = mapped_column(nullable=True)
    time_of_end: Mapped[datetime | None] = mapped_column(nullable=True)

    def __str__(self) -> str:
        return self.full_name

    def dir_name(self, config: Config) -> str:
        path = self.short_name if config.fs_course_default_shortname else self.full_name
        return sanitize_path(path, is_dir=True, config=config)


class MediaType(Enum):
    document = 1
    extern = 2
    video = 3

    # TODO: Do I really need that big of a distinction?
    corrupted_on_disk = 10
    not_available = 11
    not_available_for_legal_reasons = 12

    hardlink = 20

    def __gt__(self, other: MediaType) -> bool:
        return self.value > other.value


class MediaState(Enum):
    discovered = "media_url"
    bad = "bad_url"


class NormalizedDocument(TypedDict):
    url: str
    course_id: int
    media_type: MediaType
    relative_path: str

    name: str | None
    size: int | None

    isis_ctime: int | None
    isis_mtime: int | None


# https://mypy.readthedocs.io/en/stable/literal_types.html#tagged-unions for size
class MediaURL(DataBase):  # type:ignore[valid-type, misc]
    """
    This class is the representation of a crawled url and it's corresponding download url.

    It should always be in a valid state, however the valid state does not encompass it being downloadable.
    This could be due to a number of factors that can also change between runs of isisdl.
    As downloading a MediaURL resolves this problem completely (we don't have to track anymore if the url is valid or not), only store the failed data.

    It should always be checked, if corrupted MediaURLs are still corrupted and all those that haven't been downloaded have to be re-checked

    TODO: Is MediaURL immutable?
    """
    __tablename__ = "media_urls"

    url: Mapped[str] = mapped_column(String(1337), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    media_state: Mapped[MediaState] = mapped_column(SQLEnum(MediaState), nullable=False, default=MediaState.discovered)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)

    discovered_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_size: Mapped[int | None] = mapped_column(nullable=True)
    discovered_ctime: Mapped[datetime | None] = mapped_column(nullable=True)
    discovered_mtime: Mapped[datetime | None] = mapped_column(nullable=True)

    time_discovered: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now())
    time_last_checked: Mapped[datetime | None] = mapped_column(nullable=True)
    times_checked: Mapped[int] = mapped_column(nullable=False, default=0)

    course: Mapped[Course] = relationship("Course")
    downloads: Mapped[list[DownloadedURL]] = relationship("DownloadedURL")  # There may be 0, 1 or multiple downloaded files for a single MediaURL

    def should_download(self) -> bool:
        if len(self.downloads) > 0:
            return False

        if self.times_checked == 0:
            return True

        # TODO: Fill in other gaps

        # TODO: Check if the parameters are good
        delta = timedelta(seconds=(self.times_checked * 5) ** 3 * 60)
        return bool(datetime.now() > self.last_checked + delta)

    def temp_path(self, config: Config) -> Path:
        return Path(working_dir_location) / temp_file_location / self.course.dir_name(config) / checksum_algorithm(self.url.encode()).hexdigest()


class BadURL(MediaURL):  # type:ignore[valid-type, misc]
    """
    This class represents a URL which could not be downloaded in the past.
    We can't know for sure if the URL still can't be downloaded, but we can try again.
    """
    __tablename__ = "bad_urls"
    __table_args__ = (ForeignKeyConstraint(["url", "course_id", "version"], ["media_urls.url", "media_urls.course_id", "media_urls.version"]),)

    url: Mapped[str] = mapped_column(String(1337), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    last_checked: Mapped[datetime] = mapped_column(nullable=False)

    def should_retry(self) -> bool:
        return False  # TODO: Implement this


class TempURL(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represents a downloaded piece of media in the temporary directory.
    It has to be checked for conflicts and duplicates.
    """
    __tablename__ = "temp_urls"
    __table_args__ = (ForeignKeyConstraint(["url", "course_id", "version"], ["media_urls.url", "media_urls.course_id", "media_urls.version"]),)

    url: Mapped[str] = mapped_column(String(1337), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    time_downloaded: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now())

    media_url: Mapped[MediaURL] = relationship("MediaURL")

    def temp_path(self, config: Config) -> Path:
        return self.media_url.temp_path(config)

    def final_path(self, config: Config) -> Path:
        base, ext = os.path.split(self.name)
        return Path(working_dir_location) / self.media_url.course.dir_name(config) / self.media_url.relative_path / self.name if self.version == 0 else f"{base}.{self.version}.{ext}"


class DownloadedURL(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represent a piece of media that has been downloaded.
    """
    __tablename__ = "downloaded_urls"

    # Link each instance to a MediaURL
    __table_args__ = (ForeignKeyConstraint(["url", "course_id", "version"], ["media_urls.url", "media_urls.course_id", "media_urls.version"]),)

    url: Mapped[str] = mapped_column(String(1337), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=0)

    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)

    time_downloaded: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now())


class Error:
    """
    This class acts as an async None type. Its purpose is, as the name implies, to signalize that an error has occurred.
    This can't be done by returning None as it does not define `__aenter__` and `__aexit__`.
    """

    async def __aenter__(self) -> Error:
        return self

    async def __aexit__(self, exc_type: Type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> bool:
        return False


@dataclass
class AuthenticatedSession:
    session: InternetSession
    session_key: str
    api_token: str

    @staticmethod
    def calculate_timeout(url: str, times_retried: int) -> ClientTimeout:
        from isisdl.api.endpoints import MoodleAPIEndpoint

        if url == MoodleAPIEndpoint.url:
            # The API is reliable and may take a long time to complete the request. So don't timeout it.
            return ClientTimeout(None)

        elif "tubcloud.tu-berlin.de" in url:
            # The tubcloud can be *really* slow
            timeout = 25

        else:
            timeout = download_base_timeout

        return ClientTimeout(total=float(timeout + download_timeout_multiplier ** (1.7 * times_retried)))

    def get(self, url: str, **kwargs: Any) -> _RequestContextManager | Error:
        # TODO: Check if the server is available and accepts connects to 443 or 80
        if not url.startswith("http"):
            url = "https://" + url

        for i in range(num_tries_download):
            try:
                return self.session.get(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception as ex:
                logger.error(f"{ex}")
                time.sleep(download_static_sleep_time)

        return Error()

    def post(self, url: str, data: dict[str, Any] | list[dict[str, Any]], post_json: bool, **kwargs: Any) -> _RequestContextManager | Error:
        kwargs = {"json" if post_json else "data": data}

        for i in range(num_tries_download):
            try:
                return self.session.post(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception as ex:
                logger.error(f"{ex}")
                time.sleep(download_static_sleep_time)

        return Error()

    def head(self, url: str, **kwargs: Any) -> _RequestContextManager | Error:
        for i in range(num_tries_download):
            try:
                return self.session.head(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception as ex:
                logger.error(f"{ex}")
                time.sleep(download_static_sleep_time)

        return Error()

    async def close(self) -> None:
        await self.session.close()
