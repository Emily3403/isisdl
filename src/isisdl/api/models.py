from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import TracebackType
from typing import Any, Type

from aiohttp import ClientSession as InternetSession
from aiohttp.client import _RequestContextManager
from sqlalchemy import Text, Enum as SQLEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from isisdl.db_conf import DataBase
from isisdl.settings import download_base_timeout, download_timeout_multiplier, num_tries_download, download_static_sleep_time


class Course(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)

    preferred_name: Mapped[str | None] = mapped_column(Text, nullable=True)  # TODO: When merging, does the null update also get merged?
    short_name: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)

    number_users: Mapped[int] = mapped_column(nullable=False)
    is_favorite: Mapped[bool] = mapped_column(nullable=False)

    time_of_last_access: Mapped[datetime] = mapped_column(nullable=False)
    time_of_last_modification: Mapped[datetime] = mapped_column(nullable=False)
    time_of_start: Mapped[datetime] = mapped_column(nullable=False)
    time_of_end: Mapped[datetime] = mapped_column(nullable=False)


class MediaType(Enum):
    document = 1
    extern = 2
    video = 3
    corrupted = 4
    hardlink = 5


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


class MediaContainer(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represent a piece of media that has been downloaded
    """
    __tablename__ = "media_containers"

    url: Mapped[str] = mapped_column(String(420), primary_key=True)
    download_url: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    time_created: Mapped[datetime] = mapped_column(nullable=False)
    time_modified: Mapped[datetime] = mapped_column(nullable=False)
    checksum: Mapped[str] = mapped_column(Text)

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)

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
    def calculate_timeout(url: str, times_retried: int) -> float | None:
        from isisdl.api.endpoints import MoodleAPIEndpoint

        if url == MoodleAPIEndpoint.url:
            # The API is reliable and may take a long time to complete the request. So don't timeout it.
            return None

        elif "tubcloud.tu-berlin.de" in url:
            # The tubcloud can be *really* slow
            timeout = 25

        else:
            timeout = download_base_timeout

        return float(timeout + download_timeout_multiplier ** (1.7 * times_retried))

    def get(self, url: str, **kwargs: Any) -> _RequestContextManager | Error:
        for i in range(num_tries_download):
            try:
                return self.session.get(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)

        return Error()

    def post(self, url: str, data: dict[str, Any] | list[dict[str, Any]], post_json: bool, **kwargs: Any) -> _RequestContextManager | Error:
        kwargs = {"json" if post_json else "data": data}

        for i in range(num_tries_download):
            try:
                return self.session.post(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)

        return Error()

    def head(self, url: str, **kwargs: Any) -> _RequestContextManager | Error:
        for i in range(num_tries_download):
            try:
                return self.session.head(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)

        return Error()

    async def close(self) -> None:
        await self.session.close()
