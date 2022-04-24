from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from sqlite3 import Connection, Cursor
from threading import Lock
from typing import TYPE_CHECKING, cast, Set, Dict, List, Any, Union, DefaultDict, Iterable

from isisdl.settings import database_file_location

if TYPE_CHECKING:
    from isisdl.backend.request_helper import MediaContainer


class DatabaseHelper:
    con: Connection
    cur: Cursor

    __slots__ = tuple(__annotations__)  # type: ignore

    lock = Lock()
    _bad_urls: Set[str] = set()
    _url_container_mapping: Dict[str, Iterable[Any]] = {}

    def __init__(self) -> None:
        from isisdl.utils import path
        self.con = sqlite3.connect(path(database_file_location), check_same_thread=False)
        self.cur = self.con.cursor()
        self.create_default_tables()

        # This leads to *way* better performance on slow drives.
        self.cur.execute("PRAGMA synchronous = OFF")

        self._bad_urls.update(self.get_bad_urls())
        self._url_container_mapping.update(self.get_containers())

    def create_default_tables(self) -> None:
        with self.lock:
            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS fileinfo
                (name text, url text, download_url text, location text, time int, course_id int, media_type int, size int, checksum text, UNIQUE(url, course_id) ON CONFLICT REPLACE)
            """)

            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS json_strings
                (id text primary key unique, json text)
            """)

    def get_state(self) -> Dict[str, List[Any]]:
        res: Dict[str, List[Any]] = {}
        with self.lock:
            names = self.cur.execute("""SELECT name FROM sqlite_master where type = 'table' """).fetchall()
            for name in names:
                res[name[0]] = self.cur.execute(f"""SELECT * FROM {name[0]}""").fetchall()

        return res

    def close_connection(self) -> None:
        self.cur.close()
        self.con.close()

    def _get_attr_by_equal(self, attr: str, eq_val: str, eq_name: str, table: str = "fileinfo") -> Any:
        with self.lock:
            res = self.cur.execute(f"""SELECT {attr} FROM {table} WHERE {eq_name} = ?""", (eq_val,)).fetchone()

        if res is None:
            return None

        if len(res) == 1:
            return res[0]
        return res

    def get_database_version(self) -> int:
        from isisdl.utils import Config

        config = self.get_config()
        if "database_version" in config:
            if config["database_version"] is None:
                return int(Config.default("database_version"))
            elif isinstance(config["database_version"], int):
                return config["database_version"]
            else:
                assert False

        if config == {}:
            return int(Config.default("database_version"))

        return 1

    def does_checksum_exist(self, checksum: str) -> bool:
        return bool()

    def delete_file_by_checksum(self, checksum: str) -> None:
        with self.lock:
            self.cur.execute("""DELETE FROM fileinfo WHERE checksum = ?""", (checksum,))
            self.con.commit()

        DatabaseHelper._url_container_mapping = self.get_containers()

    def add_pre_container(self, file: MediaContainer) -> None:
        tup = (file._name, file.url, file.download_url, str(file.path), file.time, file.course.course_id, file.media_type.value, file.size, file.checksum)

        with self.lock:
            self.cur.execute("""
                INSERT OR REPLACE INTO fileinfo values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, tup)
            self.con.commit()

        self._url_container_mapping[f"{file.url} {file.course.course_id}"] = tup

    def add_pre_containers(self, files: List[MediaContainer]) -> None:
        with self.lock:
            self.cur.executemany("""
                INSERT OR REPLACE INTO fileinfo values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(file._name, file.url, file.download_url, str(file.path), file.time, file.course.course_id, file.media_type.value, file.size, file.checksum) for file in files])
            self.con.commit()

        self._url_container_mapping.update(self.get_containers())

    def get_checksums_per_course(self) -> Dict[int, Set[str]]:
        ret = defaultdict(set)
        with self.lock:
            for course_id, checksum in self.cur.execute("""SELECT course_id, checksum from fileinfo WHERE checksum IS NOT NULL""").fetchall():
                ret[course_id].add(checksum)

        return ret

    def set_config(self, config: Dict[str, Union[bool, str, int, None, Dict[int, str]]]) -> None:
        with self.lock:
            self.cur.execute("""
                INSERT OR REPLACE INTO json_strings VALUES (?, ?)
            """, ("config", json.dumps(config)))
            self.con.commit()

    def get_config(self) -> DefaultDict[str, Union[bool, str, int, None, Dict[int, str]]]:
        with self.lock:
            data = self.cur.execute("SELECT json from json_strings where id=\"config\"").fetchone()
            if data is None:
                return defaultdict(lambda: None)

            if len(data) == 0:
                return defaultdict(lambda: None)

            return defaultdict(lambda: None, json.loads(data[0]))

    def add_bad_url(self, url: str) -> None:
        with self.lock:
            _data = self.cur.execute("SELECT json FROM json_strings where id=\"bad_url_cache\"").fetchone()
            if _data is None or len(_data) == 0:
                data = []
            else:
                data = json.loads(_data[0])

            data.append(url)
            if len(data) != len(set(data)):
                from isisdl.utils import logger
                logger.assert_fail("len(data) != len(set(data))")

            self.cur.execute("INSERT OR REPLACE INTO json_strings VALUES (?, ?)", ("bad_url_cache", json.dumps(data)))
            self.con.commit()
            self._bad_urls.add(url)

    def get_bad_urls(self) -> List[str]:
        with self.lock:
            data = self.cur.execute("SELECT json FROM json_strings where id=\"bad_url_cache\"").fetchone()
            if data is None:
                return []

            if len(data) == 0:
                return []

            if data[0] is None:
                return []

            return cast(List[str], json.loads(data[0]))

    def get_containers(self) -> Dict[str, Iterable[Any]]:
        with self.lock:
            res = self.cur.execute("SELECT * FROM fileinfo").fetchall()

        return {f"{item[1]} {item[5]}": item for item in res}

    def get_checksums(self) -> Set[str]:
        with self.lock:
            res = self.cur.execute("SELECT checksum FROM fileinfo").fetchall()

        return set(map(lambda x: str(x[0]), res))

    def know_url(self, url: str, course_id: int) -> Union[bool, Iterable[Any]]:
        if url in self._bad_urls:
            return False

        info = self._url_container_mapping.get(f"{url} {course_id}", None)
        if info is None:
            return True

        return info

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
