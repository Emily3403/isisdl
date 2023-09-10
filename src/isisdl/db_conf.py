from __future__ import annotations

from logging import error
from typing import Type, Any, Callable, TypeVar

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, DeclarativeMeta, sessionmaker, Session as DatabaseSession

from isisdl.settings import error_exit, database_url_location, fallback_database_url, is_testing
from isisdl.utils import T, KT

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
    error_exit(3, f"Database connection failed with the url `{database_url}`:\n{ex}")


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
DB_T = TypeVar("DB_T", bound=DatabaseObject)


def get_n_dbs(n: int) -> list[DatabaseSession]:
    return [DatabaseSessionMaker() for _ in range(n)]


def init_database() -> None:
    DataBase.metadata.create_all(bind=database_engine)


def add_object_to_database(db: DatabaseSession, it: T) -> T | None:
    try:
        db.add(it)
        db.commit()
    except SQLAlchemyError as e:
        error(f"Inserting into the database failed: \"{e}\"")

        db.rollback()
        if is_testing:
            raise

        return None

    return it


def add_objects_to_database(db: DatabaseSession, it: list[T]) -> list[T] | None:
    try:
        db.add_all(it)
        db.commit()
    except SQLAlchemyError as e:
        error(f"Inserting into the database failed: \"{e}\"")

        db.rollback()
        if is_testing:
            raise

        return None

    return it


def add_or_update_objects_to_database(
    db: DatabaseSession, existing_items: dict[KT, DB_T], new_data: list[dict[str, T]], db_type: Type[DB_T],
    lookup_func: Callable[[dict[str, T]], KT], attr_translator: dict[str, str],
    type_translator: dict[str, Callable[[T], Any]], attr_update_blacklist: set[str] | None = None
) -> list[DB_T] | None:
    """
    This function is a hell of a generic mess, however it is necessary as sqlalchemy does not implement the `db.merge` method for multiple objects.
    Performance wise, I cannot tolerate making a database query for each `DownloadableMediaContainer` as there might be thousands of objects which would result in thousands of database queries.

    Conceptually, it gets some existing items that are a mapping from the primary key(s) to the database items.
    Additionally, it also gets some new data and with the `lookup_func` it is able to query the dictionary for the key.
    If the key is not found, the object is created and added to the database. Otherwise, it is updated with the new data.

    Parameters:
    - db (DatabaseSession): The database session object.
    - existing_items (dict[KT, DB_T]): A dictionary of existing items in the database, mapped from primary key to database object.
    - new_data (list[dict[str, Any]]): A list of new data to be added or updated in the database.
    - db_type (Type[DB_T]): The type of the database object.
    - lookup_func (Callable[[dict[str, Any]], KT]): A function to lookup existing items using a dictionary item.
    - attr_translator (dict[str, str]): A dictionary to translate attribute names from new data to the database object.
        It is expected to have keys of the db_type and values from new_data.
        This decision might be unintuitive at first, however it has been done to allow mapping of the same attribute to multiple database attributes.
    - type_translator (dict[str, Callable[[Any], Any]]): A dictionary to translate attribute values from new data to the database object.
        It is expected to have keys of the db_type. It must not be complete, attributes that are not mapped, are mapped with the identity function.
    - attr_update_blacklist (set[str]): A set of attribute names from the `db_type` to exclude from updates.
    """

    def translate_attribute(db_attr: str, data_attr: str, dict_item: dict[str, T]) -> Any:
        return type_translator.get(db_attr, lambda x: x)(dict_item[data_attr])

    all_objects: list[DB_T] = []

    for dict_item in new_data:
        maybe_item = existing_items.get(lookup_func(dict_item))

        if maybe_item is None:
            kwargs = {}
            for db_type_attr, new_data_attr in attr_translator.items():
                kwargs[db_type_attr] = translate_attribute(db_type_attr, new_data_attr, dict_item)

            db_item = db_type(**kwargs)

        else:
            for db_type_attr, new_data_attr in attr_translator.items():
                if attr_update_blacklist is not None and db_type_attr in attr_update_blacklist:
                    continue

                setattr(maybe_item, db_type_attr, translate_attribute(db_type_attr, new_data_attr, dict_item))

            db_item = maybe_item

        db.add(db_item)
        all_objects.append(db_item)

    try:
        db.commit()
    except SQLAlchemyError as e:
        error(f"Merging into the database failed: \"{e}\"")

        db.rollback()
        if is_testing:
            raise

        return None

    return all_objects
