from __future__ import annotations

from enum import Enum

from sqlalchemy import Text, String, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from isisdl.db_conf import DataBase


class User(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), primary_key=True)
    password: Mapped[str] = mapped_column(Text)


class UpdatePolicy(Enum):
    none = 0
    pip = 1
    github = 2


class Config(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "config"

    # General
    database_version: Mapped[int] = mapped_column(primary_key=True)
    send_logs_to_server: Mapped[bool] = mapped_column()
    update_policy: Mapped[UpdatePolicy] = mapped_column(SQLEnum(UpdatePolicy))

    # Passwords
    pw_encrypt_password: Mapped[bool] = mapped_column()
    pw_salt: Mapped[str] = mapped_column(Text)

    # File saving options
    fs_make_subdirs: Mapped[bool] = mapped_column()
    fs_sanitize_filenames: Mapped[bool] = mapped_column()
    # If enabled, isisdl will only maintain one copy of the file, even when it changes. Otherwise, a backup of the file will be created with the timestamp of when it was created.
    fs_overwrite_updated_files: Mapped[bool] = mapped_column()

    # Downloading options
    dl_download_videos: Mapped[bool] = mapped_column()
    dl_follow_links: Mapped[bool] = mapped_column()
    dl_throttle_rate: Mapped[int | None] = mapped_column(nullable=True)
    dl_throttle_rate_autorun: Mapped[int | None] = mapped_column(nullable=True)
    dl_show_full_path: Mapped[bool] = mapped_column()


class BadUrl(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "bad_urls"

    url: Mapped[str] = mapped_column(Text, primary_key=True)
    last_checked: Mapped[datetime] = mapped_column()
    times_checked: Mapped[int] = mapped_column()
