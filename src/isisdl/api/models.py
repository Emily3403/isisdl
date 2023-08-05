from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from requests import Session as InternetSession

from sqlalchemy import Text, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from isisdl.db_conf import DataBase



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

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    download_url: Mapped[str] = mapped_column(Text)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)

    name: Mapped[str | None] = mapped_column(nullable=True)
    size: Mapped[int | None] = mapped_column(nullable=True)
    time_created: Mapped[datetime | None] = mapped_column(nullable=True)
    time_modified: Mapped[datetime | None] = mapped_column(nullable=True)

    _link_id: Mapped[str] = mapped_column(ForeignKey("downloadable_media_containers.url"))
    _course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), primary_key=True)

    course: Mapped[Course] = relationship("Course")
    link: Mapped[DownloadableMediaContainer | None] = relationship("DownloadableMediaContainer")


class MediaContainer(DataBase):  # type:ignore[valid-type, misc]
    """
    This class represent a piece of media that has been downloaded
    """
    __tablename__ = "media_containers"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    download_url: Mapped[str] = mapped_column(Text, primary_key=True)
    media_type: Mapped[MediaType] = mapped_column(SQLEnum(MediaType), nullable=False)
    parent_path: Mapped[Path] = mapped_column(nullable=False)
    _course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))

    name: Mapped[str] = mapped_column(nullable=False)
    size: Mapped[int] = mapped_column(nullable=False)
    time_created: Mapped[datetime] = mapped_column(nullable=False)
    time_modified: Mapped[datetime | None] = mapped_column(nullable=True)
    checksum: Mapped[str] = mapped_column(Text)

    course: Mapped[Course] = relationship("Course")



@dataclass
class AuthenticatedSession:
    session: InternetSession
    api_key: str
    session_token: str

