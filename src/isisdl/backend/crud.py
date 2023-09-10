from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.backend.models import User, Config, generate_key
from isisdl.db_conf import add_object_to_database
from isisdl.settings import master_password, error_exit


def store_user(db: DatabaseSession, username: str, password: str, user_id: int, password_to_encrypt: str | None, config: Config) -> User | None:
    the_password_to_encrypt = password_to_encrypt if config.pw_encrypt_password else master_password
    if the_password_to_encrypt is None:
        return None

    key = generate_key(the_password_to_encrypt, config)
    encrypted_password = Fernet(key).encrypt(password.encode()).decode()

    return add_object_to_database(db, User(username=username, encrypted_password=encrypted_password, user_id=user_id))


def create_default_config(db: DatabaseSession) -> Config | None:
    return add_object_to_database(db, Config(database_version=1))


def read_user(db: DatabaseSession) -> User | None:
    return db.execute(select(User)).scalar()


def read_config(db: DatabaseSession) -> Config:
    configs = db.execute(select(Config)).scalars().all()

    if len(configs) != 1:
        error_exit(2, f"Could not load config! Got {len(configs)} config database entries, expected 1\nPlease make sure you have set the config with `isisdl --init`!")

    return configs[0]
