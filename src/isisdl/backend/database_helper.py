from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING, Optional, cast, Set, Dict, List, Any, Union, DefaultDict

from isisdl.settings import database_file_location

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer


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
                (name text, url text primary key unique, download_url text, location text, time int, course_id int, media_type int, size int, checksum text)
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

    def get_name_by_checksum(self, checksum: str) -> Optional[str]:
        return cast(Optional[str], self._get_attr_by_equal("name", checksum, "checksum"))

    def does_checksum_exist(self, checksum: str) -> bool:
        return bool(self._get_attr_by_equal("checksum", checksum, "checksum"))

    def get_checksum_from_url(self, url: str) -> Optional[str]:
        return cast(Optional[str], self._get_attr_by_equal("checksum", url, "url"))

    def get_size_from_url(self, url: str) -> Optional[int]:
        return cast(Optional[int], self._get_attr_by_equal("size", url, "url"))

    def delete_by_checksum(self, checksum: str) -> None:
        with self.lock:
            self.cur.execute("""DELETE FROM fileinfo WHERE checksum = ?""", (checksum,))
            self.con.commit()

    def add_pre_container(self, file: PreMediaContainer) -> None:
        with self.lock:
            self.cur.execute("""
                INSERT OR REPLACE INTO fileinfo values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (file._name, file.url, file.download_url, file.location, file.time, file.course_id, file.media_type.value, file.size, file.checksum))
            self.con.commit()

    def add_pre_containers(self, files: List[PreMediaContainer]) -> None:
        """
        Returns true iff the element already existed
        """
        with self.lock:
            self.cur.executemany("""
                INSERT OR REPLACE INTO fileinfo values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(file._name, file.url, file.download_url, file.location, file.time, file.course_id, file.media_type.value, file.size, file.checksum)
                  for file in files])
            self.con.commit()

    def get_checksums_per_course(self) -> Dict[int, Set[str]]:
        ret = defaultdict(set)
        with self.lock:
            for course_id, checksum in self.cur.execute("""SELECT course_id, checksum from fileinfo""").fetchall():
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

    def get_pre_container_by_url(self, url: str) -> Optional[Any]:
        return self._get_attr_by_equal("*", url, "url")

    def add_bad_url(self, url: str) -> None:
        with self.lock:
            _data = self.cur.execute("SELECT json FROM json_strings where id=\"bad_url_cache\"").fetchone()
            if _data is None or len(_data) == 0:
                data = []
            else:
                data = json.loads(_data[0])

            data.append(url)
            if len(data) != len(set(data)):
                from isisdl.backend.utils import logger
                logger.message("Assertion failed: len(data) != len(set(data))")

            self.cur.execute("INSERT OR REPLACE INTO json_strings VALUES (?, ?)", ("bad_url_cache", json.dumps(data)))
            self.con.commit()

    def get_bad_urls(self) -> List[str]:
        with self.lock:
            data = self.cur.execute("SELECT json FROM json_strings where id=\"bad_url_cache\"").fetchone()
            if data is None:
                return []

            if len(data) == 0:
                return []

            return cast(List[str], json.loads(data[0]))

    def get_cached_pre_containers(self, course_id: int) -> Dict[str, int]:
        with self.lock:
            data = self.cur.execute(f"SELECT json FROM json_strings where id=\"video_cache_{course_id}\"").fetchone()
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
