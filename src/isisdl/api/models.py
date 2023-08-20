from __future__ import annotations

import re
import time
from base64 import standard_b64decode
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from requests import Session as InternetSession, Response, PreparedRequest, RequestException
from requests.adapters import HTTPAdapter
from sqlalchemy import Text, Enum as SQLEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from isisdl.db_conf import DataBase
from isisdl.settings import download_base_timeout, download_timeout_multiplier, num_tries_download, download_static_sleep_time


class Course(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    displayname: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class MediaType(Enum):
    document = 1
    extern = 2
    video = 3
    corrupted = 4
    hardlink = 5


class DownloadableMediaContainer(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represent a piece of media that can be downloaded
    """
    __tablename__ = "downloadable_media_containers"

    url: Mapped[str] = mapped_column(String(420), primary_key=True)
    download_url: Mapped[str] = mapped_column(Text)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)

    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[int | None] = mapped_column(nullable=True)
    time_created: Mapped[datetime | None] = mapped_column(nullable=True)
    time_modified: Mapped[datetime | None] = mapped_column(nullable=True)

    _course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    _link_id: Mapped[str] = mapped_column(ForeignKey("downloadable_media_containers.url"))

    course: Mapped[Course] = relationship("Course")
    link: Mapped[DownloadableMediaContainer | None] = relationship("DownloadableMediaContainer")


class MediaContainer(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represent a piece of media that has been downloaded
    """
    __tablename__ = "media_containers"

    url: Mapped[str] = mapped_column(String(420), primary_key=True)
    download_url: Mapped[str] = mapped_column(Text)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    _course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    time_created: Mapped[datetime] = mapped_column(nullable=False)
    time_modified: Mapped[datetime | None] = mapped_column(nullable=True)
    checksum: Mapped[str] = mapped_column(Text)

    course: Mapped[Course] = relationship("Course")


class MoodleMobileAdapter(HTTPAdapter):
    def send(
            self,
            request: PreparedRequest,
            stream: bool = False,
            timeout: None | float | tuple[float, float] | tuple[float, None] = None,
            verify: bool | str = True,
            cert: None | bytes | str | tuple[bytes | str, bytes | str] = None,
            proxies: Mapping[str, str] | None = None,
    ) -> Response:
        url = request.url

        encoded_token = re.search("token=(.*)", url or "")
        if encoded_token is None:
            raise RequestException(f"Token not found as part of the URL: {url}")

        decoded_token = standard_b64decode(encoded_token.group(1)).decode().split(":::")[1]

        response = Response()
        response.status_code = 200
        response._content = bytes(decoded_token, 'utf-8')  # This sets the content that will be returned by response.text
        return response


@dataclass(slots=True)
class AuthenticatedSession:
    session: InternetSession
    session_key: str
    api_token: str

    @staticmethod
    def calculate_timeout(url: str, times_retried: int) -> float:
        if "tubcloud.tu-berlin.de" in url:
            # The tubcloud can be *really* slow
            timeout = 25
        else:
            timeout = download_base_timeout

        return float(timeout + download_timeout_multiplier ** (1.7 * times_retried))

    def get(self, url: str, **kwargs: Any) -> Response | None:
        for i in range(num_tries_download):
            try:
                return self.session.get(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)

        return None

    def post(self, url: str, data: dict[str, Any], **kwargs: Any) -> Response | None:
        for i in range(num_tries_download):
            try:
                return self.session.post(url, data=data, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)

        return None

    def head(self, url: str, **kwargs: Any) -> Response | None:
        for i in range(num_tries_download):
            try:
                return self.session.post(url, timeout=self.calculate_timeout(url, i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)

        return None
