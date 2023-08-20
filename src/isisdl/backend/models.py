from __future__ import annotations

import base64
import random
import string
from datetime import datetime
from enum import Enum
from functools import cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import Text, String, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from isisdl.db_conf import DataBase
from isisdl.settings import password_hash_algorithm, password_hash_length, password_hash_iterations, master_password


def generate_key(password: str, config: Config) -> bytes:
    kdf = PBKDF2HMAC(algorithm=password_hash_algorithm(), length=password_hash_length, salt=config.pw_salt.encode(), iterations=password_hash_iterations)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


class UpdatePolicy(Enum):
    none = 0
    pip = 1
    github = 2


class Config(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "config"

    # General
    database_version: Mapped[int] = mapped_column(primary_key=True)
    send_logs_to_server: Mapped[bool] = mapped_column(default=True)
    update_policy: Mapped[UpdatePolicy] = mapped_column(SQLEnum(UpdatePolicy), default=UpdatePolicy.pip)

    # Passwords
    pw_encrypt_password: Mapped[bool] = mapped_column(default=False)
    pw_salt: Mapped[str] = mapped_column(Text, default="".join(random.choices(string.ascii_letters + string.digits + string.punctuation, k=32)))

    # File saving options
    fs_make_subdirs: Mapped[bool] = mapped_column(default=True)
    fs_sanitize_filenames: Mapped[bool] = mapped_column(default=False)
    # If enabled, isisdl will only maintain one copy of the file, even when it changes. Otherwise, a backup of the file will be created with the timestamp of when it was created.
    fs_overwrite_updated_files: Mapped[bool] = mapped_column(default=True)

    # Downloading options
    dl_download_videos: Mapped[bool] = mapped_column(default=True)
    dl_follow_links: Mapped[bool] = mapped_column(default=True)
    dl_throttle_rate: Mapped[int | None] = mapped_column(nullable=True, default=None)
    dl_throttle_rate_autorun: Mapped[int | None] = mapped_column(nullable=True, default=None)
    dl_show_full_path: Mapped[bool] = mapped_column(default=False)

    def __hash__(self) -> int:
        return hash(self.to_tuple())

    def to_tuple(self) -> tuple[tuple[str, Any], ...]:
        return tuple((k, v) for k, v in self.__dict__.items() if not k.startswith("_sa"))


class BadUrl(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "bad_urls"

    url: Mapped[str] = mapped_column(String(420), primary_key=True)
    last_checked: Mapped[datetime] = mapped_column()
    times_checked: Mapped[int] = mapped_column()


class User(DataBase):  # type:ignore[valid-type, misc]
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), primary_key=True)
    encrypted_password: Mapped[str] = mapped_column(Text)

    @cache
    def decrypt_password(self, config: Config) -> str | None:
        if not config.pw_encrypt_password:
            key = generate_key(master_password, config)
            try:
                return Fernet(key).decrypt(self.encrypted_password.encode()).decode()
            except InvalidToken:
                return None

        return None
