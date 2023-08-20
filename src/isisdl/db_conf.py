from __future__ import annotations

from typing import Type

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, DeclarativeMeta, sessionmaker, Session as DatabaseSession

from isisdl.settings import error_exit, database_url_location, fallback_database_url

# This creates a connection to the database. With it, Sessions can be instantiated.
try:
    with open(database_url_location) as f:
        database_url = f.readline().strip()

except Exception:
    database_url = fallback_database_url

try:
    if "sqlite" in database_url:
        connect_args = {"check_same_thread": False}
        isolation_level = "SERIALIZABLE"
    else:
        connect_args = {}
        isolation_level = "READ COMMITTED"

    database_engine = create_engine(database_url, connect_args=connect_args, isolation_level=isolation_level)
    database_engine.connect()

except Exception as ex:
    error_exit(1, f"Database connection failed with the url `{database_url}`:\n{ex}")


class DatabaseObject:
    __tablename__: str
    __allow_unmapped__ = True

    def __str__(self) -> str:
        return f"{type(self).__name__}"

    def __repr__(self) -> str:
        return self.__str__()


# This Callable can be used to create new Session objects for interacting with a database
DatabaseSessionMaker = sessionmaker(autocommit=False, bind=database_engine)
DataBase: Type[DeclarativeMeta] = declarative_base(cls=DatabaseObject)


def get_n_dbs(n: int) -> list[DatabaseSession]:
    return [DatabaseSessionMaker() for _ in range(n)]


def init_database() -> None:
    DataBase.metadata.create_all(bind=database_engine)
