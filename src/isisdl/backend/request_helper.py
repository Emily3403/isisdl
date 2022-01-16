from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from typing import Optional, Dict, List, Any, cast, Tuple
from urllib.parse import urlparse, urljoin

from isisdl.backend.downloads import SessionWithKey, MediaType, MediaContainer, Status, DownloadThrottler
from isisdl.backend.utils import User, path, sanitize_name, args, on_kill, database_helper, _course_downloader_transformation
from isisdl.settings import course_dir_location, enable_multithread, checksum_algorithm, is_testing, checksum_num_bytes


@dataclass
class PreMediaContainer:
    name: str
    file_id: str
    url: str
    location: str
    time: datetime
    course_id: int
    is_video: bool
    size: int = -1
    checksum: Optional[str] = None

    @classmethod
    def from_api(cls, file_dict: Dict[str, Any], file_id: str, course: Course) -> PreMediaContainer:
        file_id = f"{file_id}_{checksum_algorithm(file_dict['fileurl'].encode()).hexdigest()}"

        return cls.from_course(file_dict["filename"], file_id, file_dict["fileurl"], course, file_dict["timemodified"], file_dict["filepath"], file_dict["filesize"])

    @classmethod
    def from_course(cls, name: str, file_id: str, url: str, course: Course, last_modified: int, relative_location: str = "", size: int = -1) -> PreMediaContainer:
        # Sanitize bad names
        relative_location = relative_location.strip("/")
        if relative_location:
            if database_helper.get_size_from_file_id(file_id) is None:
                os.makedirs(course.path(sanitize_name(relative_location)), exist_ok=True)

        is_video = "mod/videoservice/file.php" in url
        if is_video:
            relative_location = os.path.join(relative_location, "Videos")

        sanitized_url = urljoin(url, urlparse(url).path)

        location = course.path(sanitize_name(relative_location))
        time = datetime.fromtimestamp(last_modified)

        if "webservice/pluginfile.php" not in url and "mod/videoservice/file.php" not in url:
            # TODO: Server
            pass

        return cls(name, file_id, sanitized_url, location, time, course.course_id, is_video, size)

    def dump(self) -> bool:
        assert self.checksum is not None
        return database_helper.add_pre_container(self)

    def calculate_online_checksum(self, s: SessionWithKey) -> Tuple[str, int]:
        while True:
            running_download = s.get_(self.url, params={"token": s.token}, stream=True)

            if running_download is None:
                continue

            if not running_download.ok:
                assert False

            break

        chunk = running_download.raw.read(checksum_num_bytes, decode_content=True)
        size = len(chunk)

        return checksum_algorithm(chunk + str(size).encode()).hexdigest(), size

    def __hash__(self) -> int:
        return self.file_id.__hash__()


@dataclass
class Course:
    name: str
    course_id: int

    @classmethod
    def from_dict(cls, info: Dict[str, Any]) -> Course:
        name = cast(str, info["displayname"])
        id = cast(int, info["id"])

        return cls(name, id)

    def __post_init__(self) -> None:
        self.prepare_dirs()

    def prepare_dirs(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(self.path(item), exist_ok=True)

    def download_videos(self, s: SessionWithKey) -> List[PreMediaContainer]:
        if args.disable_videos:
            return []

        url = "https://isis.tu-berlin.de/lib/ajax/service.php"
        # Thank you isia-tub for this data <3
        video_data = [{
            "index": 0,
            "methodname": "mod_videoservice_get_videos",
            "args": {"coursemoduleid": 0, "courseid": self.course_id}
        }]

        videos_res = s.get_(url, params={"sesskey": s.key}, json=video_data)
        if videos_res is None:
            return []

        videos_json = videos_res.json()[0]

        if videos_json["error"]:
            return []

        return [PreMediaContainer.from_course(item["title"].strip() + item["fileext"], item["id"], item["url"], self, item["timecreated"], size=item["duration"])
                for item in videos_json["data"]["videos"]]

    def download_documents(self, helper: RequestHelper) -> List[PreMediaContainer]:
        if args.disable_documents:
            return []

        content = helper.post_REST("core_course_get_contents", {"courseid": self.course_id})
        if content is None:
            return []

        content = cast(List[Dict[str, Any]], content)

        all_content: List[PreMediaContainer] = []
        for week in content:
            file: Dict[str, Any]
            for file in week["modules"]:
                if "url" not in file:
                    continue

                url: str = file["url"]
                # This is a definite blacklist on stuff we don't want to follow.
                ignore = re.match(
                    ".*mod/(?:"
                    "forum|url|choicegroup|assign|videoservice|feedback|choice|quiz|glossary|questionnaire|scorm|etherpadlite|lti|h5pactivity|"
                    "page"
                    ")/.*", url
                )

                if ignore is not None:
                    # Blacklist hit
                    continue

                if re.match(".*mod/(?:folder|resource)/.*", url) is None:
                    # TODO: server
                    pass

                if "contents" not in file:
                    # TODO: Server
                    continue

                prev_len = len(all_content)
                if "contents" in file:
                    for item in file["contents"]:
                        all_content.append(PreMediaContainer.from_api(item, file["id"], self))

                if len(all_content) == prev_len:
                    known_bad_urls = {
                        "https://isis.tu-berlin.de/mod/folder/view.php?id=1145174"
                    }

                    if url not in known_bad_urls:
                        # TODO: Server
                        pass

        return all_content

    def path(self, *args: str) -> str:
        """
        Custom path function that prepends the args with the `download_dir` and course name.
        """
        return path(course_dir_location, sanitize_name(self.name), *args)

    @property
    def ok(self) -> bool:
        if args.whitelist != [True] and self in args.whitelist:
            return True

        return self in args.whitelist and self not in args.blacklist

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"{self.name} ({self.course_id})"

    def __eq__(self, other: Any) -> bool:
        if other is True:
            return True

        if other.__class__ == self.__class__:
            return bool(self.course_id == other.course_id)

        if isinstance(other, (str, int)):
            return str(self.course_id) == str(other)

        return False

    def __hash__(self) -> int:
        return self.course_id


@dataclass
class RequestHelper:
    user: User
    session: SessionWithKey = field(init=False)
    courses: List[Course] = field(default_factory=lambda: [])
    course_id_mapping: Dict[int, Course] = field(default_factory=lambda: {})
    _meta_info: Dict[str, str] = field(default_factory=lambda: {})

    def __post_init__(self) -> None:
        self.session = SessionWithKey.from_scratch(self.user)

        self._meta_info = cast(Dict[str, str], self.post_REST("core_webservice_get_site_info"))
        self._get_courses()

        if args.verbose:
            print("I am downloading the following courses:\n" + "\n".join(item.name for item in self.courses))

    def _get_courses(self) -> None:
        res = cast(List[Dict[str, str]], self.post_REST("core_enrol_get_users_courses", {"userid": self.userid}))
        for item in res:
            course = Course.from_dict(item)

            self.course_id_mapping.update({course.course_id: course})
            database_helper.add_course(course)

            if course.ok:
                self.courses.append(course)
                if not os.path.exists(course.path()):
                    os.makedirs(course.path(), exist_ok=True)

    def post_REST(self, function: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        data = data or {}

        data.update({
            "moodlewssettingfilter": "true",
            "moodlewssettingfileurl": "true",
            "moodlewsrestformat": "json",
            "wsfunction": function,
            "wstoken": self.session.token
        })

        url = "https://isis.tu-berlin.de/webservice/rest/server.php"

        response = self.session.post_(url, data=data, params=params)

        if response is None or not response.ok:
            return None

        return response.json()

    def download_content(self) -> List[PreMediaContainer]:
        def download_videos(ret: List[PreMediaContainer], course: Course, session: SessionWithKey) -> None:
            ret.extend(course.download_videos(session))

        def download_documents(ret: List[PreMediaContainer], course: Course) -> None:
            ret.extend(course.download_documents(self))

        def download_mod_assign(ret: List[PreMediaContainer]) -> None:
            ret.extend(self.download_mod_assign())

        if enable_multithread:
            collect: List[Tuple[List[PreMediaContainer], List[PreMediaContainer]]] = [([], []) for _ in range(len(self.courses))]
            threads = []

            mod_assign: List[PreMediaContainer] = []
            mod_assign_thread = Thread(target=download_mod_assign, args=(mod_assign,))
            for col, course in zip(collect, self.courses):
                threads.append(Thread(target=download_documents, args=(col[0], course)))
                threads.append(Thread(target=download_videos, args=(col[1], course, self.session)))

            mod_assign_thread.start()
            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join()

            mod_assign_thread.join()

            documents, videos = [], []
            for item in collect:
                documents.extend(item[0])
                videos.extend(item[1])

        else:
            mod_assign = self.download_mod_assign()
            documents, videos = [], []
            for course in self.courses:
                documents.extend(course.download_documents(self))
                videos.extend(course.download_videos(self.session))

        def sort(lst: List[PreMediaContainer]) -> List[PreMediaContainer]:
            return sorted(lst, key=lambda x: x.time, reverse=True)

        # Download the newest files first
        return sort(documents) + sort(mod_assign) + sort(videos)

    def download_mod_assign(self) -> List[PreMediaContainer]:
        if args.disable_documents:
            return []

        all_content = []
        _assignments = self.post_REST('mod_assign_get_assignments')
        if _assignments is None:
            return []

        assignments = cast(Dict[str, Any], _assignments)

        allowed_ids = {item.course_id for item in self.courses}
        for course in assignments["courses"]:
            if course["id"] in allowed_ids:
                for assignment in course["assignments"]:
                    for file in assignment["introattachments"]:
                        file["filepath"] = assignment["name"]
                        all_content.append(PreMediaContainer.from_api(file, assignment["id"], self.course_id_mapping[course["id"]]))

        # TODO: Also get the submission contents.
        return all_content

    @property
    def userid(self) -> str:
        return self._meta_info["userid"]


def check_for_conflicts_in_files(files: List[PreMediaContainer]) -> None:
    conflicts = defaultdict(list)
    for item in files:
        conflicts[item.name].append(item)

    items: List[List[PreMediaContainer]] = [sorted(item, key=lambda x: x.time if x.time is not None else -1) for item in conflicts.values() if len(item) != 1]
    for row in items:
        locations: Dict[str, List[PreMediaContainer]] = defaultdict(list)
        for item in row:
            locations[item.location].append(item)

        locations = {k: v for k, v in locations.items() if len(v) > 1}

        # TODO: Maybe filter out duplicates by file size

        # TODO: Server

        for new_row in locations.values():
            for i, item in enumerate(new_row):
                basename, ext = os.path.splitext(item.name)
                item.name = basename + f"({i}-{len(new_row) - 1})" + ext


class CourseDownloader:
    helper: Optional[RequestHelper] = None

    def __init__(self, user: User):
        self.user = user

    def start(self) -> None:
        self.make_helper()

        pre_containers = self.build_files()

        check_for_conflicts_in_files(pre_containers)

        if is_testing:
            pre_containers = _course_downloader_transformation(pre_containers)

        media_containers = self.make_files(pre_containers)
        global downloading_files
        downloading_files = media_containers

        # Make the runner a thread in case of a user needing to exit the program → downloading is done in the main thread
        global status
        throttler = DownloadThrottler()
        status = Status(len(media_containers), args.num_threads, throttler)
        downloader = Thread(target=self.download_files, args=(media_containers, throttler))

        downloader.start()
        status.start()

        downloader.join()
        status.join(0)

    def make_helper(self) -> None:
        self.helper = RequestHelper(self.user)

    def build_files(self) -> List[PreMediaContainer]:
        assert self.helper is not None

        return self.helper.download_content()

    def make_files(self, files: List[PreMediaContainer]) -> List[MediaContainer]:
        assert self.helper is not None

        new_files = [MediaContainer.from_pre_container(file, self.helper.session) for file in files]
        filtered_files = [item for item in new_files if item is not None]

        return filtered_files

    def download_files(self, files: List[MediaContainer], throttler: DownloadThrottler) -> None:
        def download(file: MediaContainer) -> None:
            assert status is not None
            if enable_multithread:
                thread_id = int(threading.current_thread().name.split("T_")[-1])
            else:
                thread_id = 0

            status.add(thread_id, file)
            file.download(throttler)
            status.finish(thread_id)

        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads, thread_name_prefix="T") as ex:
                list(ex.map(download, files))
        else:
            for file in files:
                download(file)

    @staticmethod
    @on_kill()
    def shutdown_running_downloads(*_: Any) -> None:
        if downloading_files is None:
            return

        for item in downloading_files:
            item.stop()

        if status is not None:
            status.shutdown()

        # Now wait for the downloads to finish
        while not all(item.done for item in downloading_files):
            time.sleep(0.25)


status: Optional[Status] = None
downloading_files: Optional[List[MediaContainer]] = None
