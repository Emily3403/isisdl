from __future__ import annotations

import sqlite3
from collections import defaultdict
from threading import Lock
from typing import TYPE_CHECKING, Optional, cast, Set, Dict, List

from isisdl.share.settings import database_file_location
from isisdl.share.utils import path

if TYPE_CHECKING:
    from isisdl.backend.request_helper import PreMediaContainer, Course


class DatabaseHelper:
    lock: Lock = Lock()

    def __init__(self):
        try:
            self.con = sqlite3.connect(f"file:{path(database_file_location)}?mode=rw", uri=True, check_same_thread=False)
            self.cur = self.con.cursor()

        except sqlite3.OperationalError:
            # No database found → create a new one
            self.con = sqlite3.connect(path(database_file_location), check_same_thread=False)
            self.cur = self.con.cursor()

            self.cur.execute("""
                CREATE TABLE fileinfo
                (name text, file_id text primary key, url text, time int, course_id int, checksum text)
            """)

            self.cur.execute("""
                CREATE TABLE courseinfo
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

    def get_course_name_and_ids(self) -> List[str]:
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

    def get_state(self):
        res = []
        with DatabaseHelper.lock:
            for database in ["fileinfo", "courseinfo"]:
                self.cur.execute(f"""SELECT * from {database}""")
                res.append(self.cur.fetchall())

        return res

    def get_checksums_per_course(self) -> Dict[str, Set[str]]:
        ret = defaultdict(set)
        with DatabaseHelper.lock:
            for course_name, checksum in self.cur.execute("""SELECT courseinfo.name, checksum from fileinfo INNER JOIN courseinfo on fileinfo.course_id = courseinfo.id""").fetchall():
                ret[course_name].add(checksum)

        return ret


database_helper = DatabaseHelper()
