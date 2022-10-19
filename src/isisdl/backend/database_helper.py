from __future__ import annotations

import json
import secrets
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from sqlite3 import Connection, Cursor
from threading import Lock
from typing import TYPE_CHECKING, cast, Set, Dict, List, Any, Union, DefaultDict, Iterable, Tuple

from isisdl.settings import database_file_location, error_text, bad_url_cache_reeval_times_mul, bad_url_cache_reeval_exp, \
    bad_url_cache_reeval_static_mul, random_salt_length

if TYPE_CHECKING:
    from isisdl.backend.request_helper import MediaContainer


@dataclass
class BadUrl:
    url: str
    last_checked: int
    times_checked: int

    def dump(self) -> Tuple[str, int, int]:
        return self.url, self.last_checked, self.times_checked

    def __hash__(self) -> int:
        return self.url.__hash__()

    def __eq__(self, other: Any) -> bool:
        if self.__class__ == other.__class__:
            return bool(self.url == other.url)

        elif isinstance(other, str):
            return bool(self.url == other)

        return False

    def should_download(self) -> bool:
        return bool(time.time() > self.last_checked + (self.times_checked * bad_url_cache_reeval_times_mul) ** bad_url_cache_reeval_exp * bad_url_cache_reeval_static_mul)


class DatabaseHelper:
    con: Connection
    cur: Cursor

    __slots__ = tuple(__annotations__)  # type: ignore

    lock = Lock()
    _bad_urls: dict[str, BadUrl] = dict()
    _url_container_mapping: dict[str, Iterable[Any]] = {}
    _hardlinks: DefaultDict[MediaContainer, list[MediaContainer]] = defaultdict(list)

    def __init__(self) -> None:
        from isisdl.utils import path
        self.con = sqlite3.connect(path(database_file_location), check_same_thread=False)
        self.cur = self.con.cursor()
        self.create_default_tables()

        # This leads to *way* better performance on slow drives with high latency.
        self.cur.execute("PRAGMA synchronous = OFF")

        self._bad_urls.update(self.get_bad_urls())
        self._url_container_mapping.update(self.get_containers())
        self._hardlinks.update((self.produce_hardlinks()))

        self.maybe_insert_database_version()
        self.maybe_insert_salt()

        self.know_url("uwu.com", 123)

    def create_default_tables(self) -> None:
        with self.lock:
            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS fileinfo

                (
                name text,
                url text,
                download_url text,
                time int,
                course_id int,
                media_type int,
                size int,
                checksum text,
                UNIQUE(url, course_id) ON CONFLICT REPLACE
                )
            """)

            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS config

                (
                key text primary key unique,
                value text
                )
            """)

            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS bad_url_cache

                (
                url text primary key unique,
                last_checked int,
                times_checked int
                )
            """)

            self.con.commit()

    def close_connection(self) -> None:
        self.cur.close()
        self.con.close()

    def get_state(self) -> Dict[str, List[Any]]:
        res: Dict[str, List[Any]] = {}
        with self.lock:
            names = self.cur.execute("""SELECT name FROM sqlite_master where type = 'table' """).fetchall()
            for name in names:
                res[name[0]] = self.cur.execute(f"""SELECT * FROM {name[0]}""").fetchall()

        return res

    def _get_attr_by_equal(self, attr: str, eq_val: str, eq_name: str, table: str = "fileinfo") -> Any:
        with self.lock:
            res = self.cur.execute(f"""SELECT {attr} FROM {table} WHERE {eq_name} = ?""", (eq_val,)).fetchone()

        if res is None:
            return None

        if len(res) == 1:
            return res[0]
        return res

    def get_database_version(self) -> int:
        # TODO: This function will fail with older databases. Make sure it doesn't.
        def default_version() -> int:
            from isisdl.utils import Config
            return int(Config.default("database_version"))

        version = self.get_config_key("database_version")

        if version is None:
            return default_version()

        if type(version) != int:
            print(f"{error_text} Malformed config in database: Expected type 'int' for key version. Got {type(version)}.\nBailing out!")

        assert type(version) == int
        return version

    def maybe_insert_database_version(self) -> None:
        from isisdl.utils import Config

        with self.lock:
            self.cur.execute("INSERT OR IGNORE into config values (?, ?)", ("database_version", json.dumps(int(Config.default("database_version")))))
            self.con.commit()

    def maybe_insert_salt(self) -> None:
        password = secrets.token_urlsafe(random_salt_length)

        with self.lock:
            self.cur.execute("INSERT OR IGNORE into config values (?, ?)", ("salt", json.dumps(password)))
            self.con.commit()

    def does_checksum_exist(self, checksum: str) -> bool:
        return bool()

    def delete_file_by_checksum(self, checksum: str) -> None:
        with self.lock:
            self.cur.execute("""DELETE FROM fileinfo WHERE checksum = ?""", (checksum,))
            self.con.commit()

        DatabaseHelper._url_container_mapping = self.get_containers()

    def add_container(self, file: MediaContainer) -> None:
        tup = (file._name, file.url, file.download_url, file.time, file.course.course_id, file.media_type.value, file.size.dump(), file.checksum)

        with self.lock:
            self.cur.execute("""
                INSERT OR REPLACE INTO fileinfo VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, tup)
            self.con.commit()

        self._url_container_mapping[f"{file.url} {file.course.course_id}"] = tup

    def add_containers(self, files: List[MediaContainer]) -> None:
        with self.lock:
            self.cur.executemany("""
                INSERT OR REPLACE INTO fileinfo VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [(file._name, file.url, file.download_url, file.time, file.course.course_id, file.media_type.value, file.size.dump(), file.checksum) for file in files])
            self.con.commit()

        self._url_container_mapping.update(self.get_containers())

    def get_checksums_per_course(self) -> Dict[int, Set[str]]:
        ret = defaultdict(set)
        with self.lock:
            for course_id, checksum in self.cur.execute("""SELECT course_id, checksum from fileinfo WHERE checksum IS NOT NULL""").fetchall():
                ret[course_id].add(checksum)

        return ret

    def set_config_key(self, key: str, value: Union[bool, str, int, None, Dict[int, str]]) -> None:
        with self.lock:
            self.cur.execute("""
                INSERT OR REPLACE INTO config VALUES (?, ?)
            """, (key, json.dumps(value)))
            self.con.commit()

    def get_config_key(self, key: str) -> bool | str | int | None | dict[int, str]:
        with self.lock:
            it = self.cur.execute("SELECT value from config WHERE key=?", (key,)).fetchone()
            assert len(it) == 1

            return cast(Union[bool, str, int, None, Dict[int, str]], json.loads(it[0]))

    def get_config(self) -> DefaultDict[str, Union[bool, str, int, None, Dict[int, str]]]:
        with self.lock:
            data = self.cur.execute("SELECT * from config").fetchall()

            return defaultdict(lambda: None, map(lambda it: (it[0], json.loads(it[1])), data))

    def add_bad_url(self, url: str) -> None:
        with self.lock:
            _data = self.cur.execute("SELECT times_checked FROM bad_url_cache where url=?", (url,)).fetchone()

            if _data is None:
                times_checked = 0
            else:
                times_checked, = _data

            bad_url = BadUrl(url, int(time.time()), times_checked + 1)

            self.cur.execute("INSERT OR REPLACE INTO bad_url_cache values (?, ?, ?)", bad_url.dump())
            self.con.commit()
            self._bad_urls[url] = bad_url

    def get_bad_urls(self) -> Dict[str, BadUrl]:
        with self.lock:
            data = self.cur.execute("SELECT * FROM bad_url_cache").fetchall()
            return dict(map(lambda it: (it[0], BadUrl(*it)), data))

    def get_containers(self) -> Dict[str, Iterable[Any]]:
        with self.lock:
            res = self.cur.execute("SELECT * FROM fileinfo").fetchall()

        return {f"{item[1]} {item[5]}": item for item in res}

    def get_checksums(self) -> Set[str]:
        with self.lock:
            res = self.cur.execute("SELECT checksum FROM fileinfo").fetchall()

        return set(map(lambda x: str(x[0]), res))

    def know_url(self, url: str, course_id: int) -> Union[bool, Iterable[Any]]:
        maybe_bad_url = self._bad_urls.get(url, None)
        if maybe_bad_url is not None:
            return maybe_bad_url.should_download()

        info = self._url_container_mapping.get(f"{url} {course_id}", None)
        if info is None:
            return True

        return info

    def set_hardlink(self, master: MediaContainer, container: MediaContainer) -> None:
        self._hardlinks[master].append(container)

    def get_hardlinks(self, container: MediaContainer) -> list[MediaContainer]:
        return self._hardlinks[container]

    def produce_hardlinks(self) -> dict[MediaContainer, list[MediaContainer]]:
        # TODO
        pass

    # TODO: Fix this

    def update_inefficient_videos(self, file: MediaContainer, estimated_efficiency: float) -> None:
        with self.lock:
            _data = self.cur.execute("SELECT json FROM json_strings where id=\"inefficient_videos\"").fetchone()
            if _data is None or len(_data) == 0:
                data = {}
            else:
                data = json.loads(_data[0])

            data[self.make_inefficient_file_name(file)] = estimated_efficiency

            self.cur.execute("INSERT OR REPLACE INTO json_strings VALUES (?, ?)", ("inefficient_videos", json.dumps(data)))
            self.con.commit()

    def get_inefficient_videos(self) -> Dict[str, float]:
        with self.lock:
            data = self.cur.execute("SELECT json FROM json_strings where id=\"inefficient_videos\"").fetchone()
            if data is None or len(data) == 0:
                return {}
            return cast(Dict[str, float], json.loads(data[0]))

    def set_total_time_compressing(self, amount: int) -> None:
        with self.lock:
            self.cur.execute("INSERT OR REPLACE INTO json_strings VALUES (?, ?)", ("total_time_compressing", json.dumps(amount)))
            self.con.commit()

    def get_total_time_compressing(self) -> int:
        data = self.cur.execute("SELECT json FROM json_strings where id=\"total_time_compressing\"").fetchone()
        if data is None or len(data) == 0:
            return 0
        return cast(int, json.loads(data[0]))

    def delete_total_time_compressing(self) -> None:
        with self.lock:
            self.cur.execute("DELETE FROM json_strings where id=\"total_time_compressing\"")
            self.con.commit()

    @staticmethod
    def make_inefficient_file_name(file: MediaContainer) -> str:
        return f"{file.course.course_id} {file._name}"

    def filetable_exists(self) -> bool:
        with self.lock:
            return bool(self.cur.execute("SELECT * FROM fileinfo").fetchone())

    # TODO: Fix this
    def delete_inefficient_videos(self) -> None:
        with self.lock:
            self.cur.execute("DELETE FROM json_strings where id=\"inefficient_videos\"")
            self.con.commit()

    def delete_file_table(self) -> None:
        with self.lock:
            self.cur.execute("""
                DROP table fileinfo
            """)

        self.create_default_tables()

    def delete_config(self) -> None:
        with self.lock:
            self.cur.execute("""
                DROP table json_strings
            """)

        self.create_default_tables()

    def delete_bad_urls(self) -> None:
        with self.lock:
            self.cur.execute("""
                DELETE FROM json_strings WHERE id = "bad_url_cache"
            """)
            self.con.commit()
