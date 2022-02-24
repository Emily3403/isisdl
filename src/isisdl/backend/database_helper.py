from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING, Optional, cast, Set, Dict, List, Any, Union, DefaultDict

from isisdl.settings import database_file_location

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer, Course


class DatabaseHelper:
    lock = Lock()

    def __init__(self) -> None:
        from isisdl.backend.utils import path
        self.con = sqlite3.connect(path(database_file_location), check_same_thread=False)
        self.cur = self.con.cursor()
        self.create_default_tables()

    def create_default_tables(self) -> None:
        with self.lock:
            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS fileinfo
                (name text, file_id text primary key unique, url text, time int, course_id int, checksum text, size int)
            """)

            self.cur.execute("""
                CREATE TABLE IF NOT EXISTS courseinfo
                (name text, id int primary key)
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

    def _get_attr_by_equal(self, attr: str, eq_val: str, eq_name: str = "file_id", table: str = "fileinfo") -> Any:
        with self.lock:
            res = self.cur.execute(f"""SELECT {attr} FROM {table} WHERE {eq_name} = ?""", (eq_val,)).fetchone()

        if res is None:
            return None

        return res[0]

    def get_name_by_checksum(self, checksum: str) -> Optional[str]:
        return cast(Optional[str], self._get_attr_by_equal("name", checksum, "checksum"))

    def get_size_from_file_id(self, file_id: str) -> Optional[int]:
        return cast(Optional[int], self._get_attr_by_equal("size", file_id))

    def add_course(self, course: Course) -> None:
        with self.lock:
            self.cur.execute("""
                INSERT OR IGNORE INTO courseinfo values (?, ?)
            """, (course.name, course.course_id))
            self.con.commit()

    def delete_by_checksum(self, checksum: str) -> None:
        with self.lock:
            self.cur.execute("""DELETE FROM fileinfo WHERE checksum = ?""", (checksum,))
            self.con.commit()

    def add_pre_container(self, file: PreMediaContainer) -> bool:
        """
        Returns true iff the element already existed
        """
        with self.lock:
            already_exists = self.cur.execute("SELECT * FROM fileinfo WHERE checksum = ?", (file.checksum,)).fetchone() is not None

            self.cur.execute("""
                INSERT OR REPLACE INTO fileinfo values (?, ?, ?, ?, ?, ?, ?)
            """, (file._name, file.file_id, file.url, int(file.time.timestamp()), file.course_id, file.checksum, file.size))
            self.con.commit()

            return already_exists

    def add_pre_containers(self, files: List[PreMediaContainer]) -> None:
        """
        Returns true iff the element already existed
        """
        with self.lock:
            self.cur.executemany("""
                INSERT OR REPLACE INTO fileinfo values (?, ?, ?, ?, ?, ?, ?)
            """, [(file._name, file.file_id, file.url, int(file.time.timestamp()), file.course_id, file.checksum, file.size) for file in files])
            self.con.commit()

    def get_checksums_per_course(self) -> Dict[str, Set[str]]:
        ret = defaultdict(set)
        with self.lock:
            for course_name, checksum in self.cur.execute("""SELECT courseinfo.name, checksum from fileinfo INNER JOIN courseinfo on fileinfo.course_id = courseinfo.id""").fetchall():
                ret[course_name].add(checksum)

        return ret

    def set_config(self, config: Dict[str, Union[bool, str, int, None]]) -> None:
        with self.lock:
            self.cur.execute("""
                INSERT OR REPLACE INTO json_strings VALUES (?, ?)
            """, ("config", json.dumps(config)))
            self.con.commit()

    def get_config(self) -> DefaultDict[str, Union[bool, str, int, None]]:
        with self.lock:
            data = self.cur.execute("SELECT json from json_strings where id=\"config\"").fetchone()
            if data is None:
                return defaultdict(lambda: None)

            if len(data) == 0:
                return defaultdict(lambda: None)

            return defaultdict(lambda: None, json.loads(data[0]))

    def set_video_cache(self, cache: Dict[str, int], course_name: str) -> None:
        with self.lock:
            self.cur.execute("""
               INSERT OR REPLACE INTO json_strings VALUES (?, ?)
            """, ("video_cache_" + course_name, json.dumps(cache)))
            self.con.commit()

    def get_video_cache(self, course_name: str) -> Dict[str, int]:
        with self.lock:
            data = self.cur.execute("SELECT json FROM json_strings where id=\"video_cache_" + course_name + "\"").fetchone()
            if data is None:
                return {}

            if len(data) == 0:
                return {}

            return cast(Dict[str, int], json.loads(data[0]))

    def get_video_cache_exists(self) -> bool:
        with self.lock:
            data = self.cur.execute("SELECT * FROM json_strings WHERE id LIKE '%video%'").fetchone()
            if data is None:
                return False

            if len(data) == 0:
                return False

            return True

    def update_inefficient_videos(self, file: PreMediaContainer, estimated_efficiency: float) -> None:
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
    def make_inefficient_file_name(file: PreMediaContainer) -> str:
        return f"{file.course_id} {file._name}"

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
