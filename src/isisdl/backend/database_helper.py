from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING, Optional, cast, Set, Dict, List, Tuple, Union, Any

from isisdl.share.settings import database_file_location
from isisdl.share.utils import path

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer, Course


class SQLiteDatabase(ABC):
    lock: Lock = Lock()

    def __init__(self):
        self.con = sqlite3.connect(path(database_file_location), check_same_thread=False)
        # self.con = sqlite3.connect(":memory:", check_same_thread=False)
        self.cur = self.con.cursor()

        self.create_default_tables()

    @abstractmethod
    def create_default_tables(self):
        ...

    def get_state(self):
        res = []
        with self.lock:
            names = self.cur.execute("""SELECT name FROM sqlite_master where type = 'table' """).fetchall()
            for name in names:
                res.append(self.cur.execute(f"""SELECT * FROM {name[0]}""").fetchall())

        return res


class DatabaseHelper(SQLiteDatabase):
    def create_default_tables(self):
        with self.lock:
            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS fileinfo
                (name text, file_id text primary key, url text, time int, course_id int, checksum text)
            """)

            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS courseinfo
                (name text, id int primary key)
            """)

    def _get_attr_by_equal(self, attr: str, eq_val: str, eq_name: str = "file_id", table: str = "fileinfo"):
        with DatabaseHelper.lock:
            res = self.cur.execute(f"""SELECT {attr} FROM {table} WHERE {eq_name} = ?""", (eq_val,)).fetchone()

        if res is None:
            return None

        return res[0]

    def get_checksum_from_file_id(self, file_id: str) -> Optional[str]:
        return cast(Optional[str], self._get_attr_by_equal("checksum", file_id))

    def get_time_from_file_id(self, file_id: str) -> Optional[int]:
        return cast(Optional[int], self._get_attr_by_equal("time", file_id))

    def get_name_by_checksum(self, checksum: str) -> Optional[str]:
        return cast(Optional[str], self._get_attr_by_equal("name", checksum, "checksum"))

    def get_course_id_by_name(self, course_name: str) -> Optional[int]:
        return cast(Optional[int], self._get_attr_by_equal("id", course_name, "name", "courseinfo"))

    def get_course_name_and_ids(self) -> List[Tuple[str, int]]:
        with DatabaseHelper.lock:
            return self.cur.execute("""SELECT * FROM courseinfo""").fetchall()

    def delete_by_checksum(self, checksum: str):
        with DatabaseHelper.lock:
            self.cur.execute("""DELETE FROM fileinfo WHERE checksum = ?""", (checksum,))
            self.con.commit()

    def add_pre_container(self, file: PreMediaContainer):
        with DatabaseHelper.lock:
            self.cur.execute("""
                INSERT OR IGNORE INTO fileinfo values (?, ?, ?, ?, ?, ?)
            """, (file.name, file.file_id, file.url, int(file.time.timestamp()), file.course_id, file.checksum))
            self.con.commit()

    def add_course(self, course: Course):
        with DatabaseHelper.lock:
            self.cur.execute("""
                INSERT OR IGNORE INTO courseinfo values (?, ?)
            """, (course.name, course.course_id))
            self.con.commit()

    def get_checksums_per_course(self) -> Dict[str, Set[str]]:
        ret = defaultdict(set)
        with DatabaseHelper.lock:
            for course_name, checksum in self.cur.execute("""SELECT courseinfo.name, checksum from fileinfo INNER JOIN courseinfo on fileinfo.course_id = courseinfo.id""").fetchall():
                ret[course_name].add(checksum)

        return ret


class ConfigHelper(SQLiteDatabase):
    def create_default_tables(self):
        with self.lock:
            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS config
                (key text unique, value text)
            """)

    def _set(self, key: str, value: Any):
        with self.lock:
            self.cur.execute("""
                INSERT OR IGNORE INTO config values (?, ?)
            """, (key, value))
            self.con.commit()

    def _get(self, key) -> Any:
        with self.lock:
            res = self.cur.execute("SELECT * FROM config where key = ?", (key,)).fetchone()
            if res is None:
                return None

            return res[0]

    def set_how_user_is_stored(self, num: int):
        self._set("user_store", num)

    def get_how_user_is_stored(self) -> int:
        return cast(int, self._get("user_store"))

    def set_user(self, username: str, password: Union[str, bytes]):
        self._set("username", username)
        self._set("password", password)

    def get_user(self) -> Tuple[str, Union[str, bytes]]:
        username = cast(str, self._get("username"))
        password = cast(Union[str, bytes], self._get("password"))

        return username, password

    def set_filename_scheme(self, num: int):
        self._set("filename_scheme", num)

    def get_filename_scheme(self) -> int:
        return cast(int, self._get("filename_scheme"))

    def delete_config(self):
        with self.lock:
            self.cur.execute("""
                DROP table config
            """)

        self.create_default_tables()


database_helper = DatabaseHelper()
config_helper = ConfigHelper()
