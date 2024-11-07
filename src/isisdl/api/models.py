from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Type, TypedDict, TYPE_CHECKING

from aiohttp import ClientSession as InternetSession
from aiohttp.client import _RequestContextManager, ClientTimeout
from sqlalchemy import Text, Enum as SQLEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from isisdl.api.rate_limiter import ThrottleType
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


class NormalizedDocument(TypedDict):
    url: str
    course_id: int
    media_type: MediaType
    relative_path: str

    name: str | None
    size: int | None
    time_created: int | None
    time_modified: int | None


# https://mypy.readthedocs.io/en/stable/literal_types.html#tagged-unions for size
class MediaURL(DataBase):  # type:ignore[valid-type, misc]
    """
    This class is a glorified URL with some metadata associated with it.
    """
    __tablename__ = "media_urls"

    url: Mapped[str] = mapped_column(String(420), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)

    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)

    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int | None] = mapped_column(nullable=True)
    time_created: Mapped[datetime | None] = mapped_column(nullable=True)
    time_modified: Mapped[datetime | None] = mapped_column(nullable=True)

    course: Mapped[Course] = relationship("Course")


class BadURL(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represents a URL which could not be downloaded in the past.
    We can't know for sure if the URL still can't be downloaded, but we can try again.
    """
    __tablename__ = "bad_urls"

    url: Mapped[str] = mapped_column(ForeignKey("media_urls.url"), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)

    last_checked: Mapped[datetime] = mapped_column(nullable=False)
    times_checked: Mapped[int] = mapped_column(nullable=False)

    media_url: Mapped[MediaURL] = relationship("MediaURL")

    def should_retry(self) -> bool:
        # TODO: Check if the parameters are good
        delta = timedelta(seconds=(self.times_checked * 5) ** 3 * 60)
        return bool(datetime.now() > self.last_checked + delta)


class TempFile(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represents a temporary file, in the `.intern/temp_courses` directory.
    It exists such that conflicts between files can be resolved.
    """

    __tablename__ = "temp_files"

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    url: Mapped[str] = mapped_column(ForeignKey("media_urls.url"), primary_key=True)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    throttle_type: Mapped[ThrottleType] = mapped_column(SQLEnum(ThrottleType), nullable=False)

    course: Mapped[Course] = relationship("Course")
    media_url: Mapped[MediaURL] = relationship("MediaURL")

    def path(self, config: Config) -> Path:
        return Path(working_dir_location) / temp_file_location / self.course.dir_name(config) / checksum_algorithm(self.download_url.encode()).hexdigest()


class MediaContainer(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represent a piece of media that has been downloaded
    """
    __tablename__ = "media_containers"

    url: Mapped[str] = mapped_column(ForeignKey("media_urls.url"), primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)

    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    time_created: Mapped[datetime] = mapped_column(nullable=False)
    time_modified: Mapped[datetime] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(Text)

    course: Mapped[Course] = relationship("Course")


class Error:
    """
    This class acts as an async None type. Its purpose is, as the name implies, to signalize that an error has occurred.
    This can't be done by returning None as it does not define `__aenter__` and `__aexit__`.
    """

    async def __aenter__(self) -> Error:
        return self

    async def __aexit__(self, exc_type: Type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> bool:
        return False


@dataclass(slots=True)
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
