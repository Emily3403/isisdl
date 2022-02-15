from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Thread
from typing import Optional, Dict, List, Any, cast, Tuple
from urllib.parse import urlparse, urljoin

from isisdl.backend.downloads import SessionWithKey, MediaType, MediaContainer, DownloadStatus, DownloadThrottler, InfoStatus, PreStatusInfo
from isisdl.backend.utils import User, path, sanitize_name, args, on_kill, database_helper, config, generate_error_message
from isisdl.settings import enable_multithread, checksum_algorithm, video_size_discover_num_threads


@dataclass
class PreMediaContainer:
    _name: str
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
            # Later: Server
            pass

        return cls(name, file_id, sanitized_url, location, time, course.course_id, is_video, size)

    @property
    def path(self) -> str:
        return os.path.join(self.location, sanitize_name(self._name))

    def dump(self) -> bool:
        assert self.checksum is not None
        return database_helper.add_pre_container(self)

    def __str__(self) -> str:
        return sanitize_name(self._name)

    def __repr__(self) -> str:
        return self.__str__()

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

    def __post_init(self) -> None:
        self.make_directories()

    def make_directories(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(self.path(item), exist_ok=True)

    def download_videos(self, s: SessionWithKey) -> List[PreMediaContainer]:
        if args.disable_videos or not config.download_videos:
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

        videos_json = videos_json["data"]["videos"]

        def find_out_size(info: Dict[str, str]) -> Optional[int]:
            req = s.head_(info["url"], allow_redirects=True)
            if req is None:
                return None

            if "content-length" not in req.headers:
                return None

            try:
                size = int(req.headers["content-length"])
                req.close()
                return size

            except ValueError:
                return None

        video_cache = database_helper.get_video_cache(self.name)
        not_found_videos = [item for item in videos_json if item["url"] not in video_cache]

        with ThreadPoolExecutor(video_size_discover_num_threads) as ex:
            sizes = list(ex.map(find_out_size, not_found_videos))

        video_cache.update({video["url"]: size for video, size in zip(videos_json, sizes)})
        database_helper.set_video_cache(video_cache, self.name)

        return [PreMediaContainer.from_course(item["title"].strip() + item["fileext"], item["id"], item["url"], self, item["date"], size=video_cache.get(item["url"], -1))
                for item in videos_json]

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
                    # Later: Server
                    pass

                if "contents" not in file:
                    # Later: Server
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
                        # Later: Server
                        pass

        return all_content

    def path(self, *args: str) -> str:
        # Custom path function that prepends the args with the course name.
        return str(path(sanitize_name(self.name), *args))

    @property
    def ok(self) -> bool:
        if config.whitelist is None and config.blacklist is None:
            return True

        if config.whitelist is None and config.blacklist is not None:
            return self.course_id not in config.blacklist

        if config.whitelist is not None and config.blacklist is None:
            return self.course_id in config.whitelist

        if config.whitelist is not None and config.blacklist is not None:
            return self.course_id in config.whitelist and self.course_id not in config.blacklist

        assert False

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

    def __lt__(self, other: Course) -> bool:
        return self.course_id < other.course_id


class RequestHelper:
    user: User
    session: SessionWithKey
    courses: List[Course]
    course_id_mapping: Dict[int, Course]
    _meta_info: Dict[str, str]
    _instance: Optional[RequestHelper] = None
    _instance_init: bool = False

    def __init__(self, user: User):
        if self._instance_init:
            return

        self.user = user
        session = SessionWithKey.from_scratch(self.user, pre_status)
        if session is None:
            print(f"I had a problem getting the user {self.user}. You have probably entered the wrong credentials.\nBailing out…")
            exit(1)

        self.session = session
        self.courses = []
        self.course_id_mapping = {}

        self._meta_info = cast(Dict[str, str], self.post_REST("core_webservice_get_site_info"))

        self.get_courses()

        RequestHelper._instance_init = True

    def __new__(cls, user: User) -> RequestHelper:
        if RequestHelper._instance is None:
            RequestHelper._instance = super().__new__(cls)

        return RequestHelper._instance

    def make_course_paths(self) -> None:
        for course in self.courses:
            if not os.path.exists(course.path()):
                os.makedirs(course.path(), exist_ok=True)
            course.make_directories()

    def get_courses(self) -> None:
        res = cast(List[Dict[str, str]], self.post_REST("core_enrol_get_users_courses", {"userid": self.userid}))
        courses = []
        for item in res:
            course = Course.from_dict(item)
            self.course_id_mapping.update({course.course_id: course})
            database_helper.add_course(course)

            if course.ok:
                courses.append(course)

        self.courses = sorted(courses, reverse=True)

    def post_REST(self, function: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        data = data or {}

        data.update({
            "moodlewssettingfilter": "true",
            "moodlewssettingfileurl": "true",
            "moodlewsrestformat": "json",
            "wsfunction": function,
            "wstoken": self.session.token,
        })

        url = "https://isis.tu-berlin.de/webservice/rest/server.php"

        response = self.session.post_(url, data=data, params=params)

        if response is None or not response.ok:
            return None

        return response.json()

    def download_content(self) -> List[PreMediaContainer]:
        exception_lock = threading.Lock()

        pre_status.set_status(PreStatusInfo.content)

        # The number of threads that are going to spawn
        pre_status.set_max_content(len(self.courses) * 2 + 1)

        def download_videos(ret: List[PreMediaContainer], course: Course, session: SessionWithKey) -> None:
            try:
                ret.extend(course.download_videos(session))

                assert pre_status.status == PreStatusInfo.content
                pre_status.status.value.append(None)
            except Exception:
                with exception_lock:
                    generate_error_message()

        def download_documents(ret: List[PreMediaContainer], course: Course) -> None:
            try:
                ret.extend(course.download_documents(self))

                assert pre_status.status == PreStatusInfo.content
                pre_status.status.value.append(None)
            except Exception:
                with exception_lock:
                    generate_error_message()

        def download_mod_assign(ret: List[PreMediaContainer]) -> None:
            try:
                ret.extend(self.download_mod_assign())

                assert pre_status.status == PreStatusInfo.content
                pre_status.status.value.append(None)

            except Exception:
                with exception_lock:
                    generate_error_message()

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
            pre_status.status.value.append(None)
            documents, videos = [], []
            for course in self.courses:
                documents.extend(course.download_documents(self))
                pre_status.status.value.append(None)
                videos.extend(course.download_videos(self.session))
                pre_status.status.value.append(None)

        def sort(lst: List[PreMediaContainer]) -> List[PreMediaContainer]:
            return sorted(lst, key=lambda x: x.time, reverse=True)

        # Download the newest files first
        all_files = sort(documents + mod_assign) + sort(videos)
        check_for_conflicts_in_files(all_files)

        return all_files

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

        return all_content

    @property
    def userid(self) -> str:
        return self._meta_info["userid"]


def check_for_conflicts_in_files(files: List[PreMediaContainer]) -> None:
    conflicts = defaultdict(list)
    for item in files:
        conflicts[item._name].append(item)

    items: List[List[PreMediaContainer]] = [sorted(item, key=lambda x: x.time if x.time is not None else -1) for item in conflicts.values() if len(item) != 1]
    for row in items:
        locations: Dict[str, List[PreMediaContainer]] = defaultdict(list)
        for item in row:
            locations[item.location].append(item)

        locations = {k: v for k, v in locations.items() if len(v) > 1}

        # Later: Server

        for new_row in locations.values():
            for i, item in enumerate(new_row):
                basename, ext = os.path.splitext(item._name)
                item._name = basename + f"({i}-{len(new_row) - 1})" + ext


class CourseDownloader:
    helper: Optional[RequestHelper] = None

    def __init__(self, user: User):
        self.user = user

    def start(self) -> None:
        global pre_status
        pre_status = InfoStatus()
        while PreStatusInfo.content.value:
            PreStatusInfo.content.value.pop()

        pre_status.start()

        self.helper = RequestHelper(self.user)

        pre_containers = self.helper.download_content()
        media_containers = self.make_files(pre_containers)

        global downloading_files
        downloading_files = media_containers
        self.helper.make_course_paths()

        # Make the runner a thread in case of a user needing to exit the program → downloading is done in the main thread
        global status
        throttler = DownloadThrottler()
        status = DownloadStatus(media_containers, args.num_threads, throttler)
        downloader = Thread(target=self.download_files, args=(media_containers, throttler))

        pre_status.stop()
        downloader.start()
        status.start()

        downloader.join()
        status.join(0)

    def make_files(self, files: List[PreMediaContainer]) -> List[MediaContainer]:
        assert self.helper is not None

        new_files = [MediaContainer.from_pre_container(file, self.helper.session) for file in files]
        filtered_files = [item for item in new_files if item is not None]

        return filtered_files

    def download_files(self, files: List[MediaContainer], throttler: DownloadThrottler) -> None:
        exception_lock = threading.Lock()

        def download(file: MediaContainer) -> None:
            assert status is not None
            if enable_multithread:
                thread_id = int(threading.current_thread().name.split("T_")[-1])
            else:
                thread_id = 0

            status.add(thread_id, file)
            try:
                file.download(throttler)
            except Exception:
                with exception_lock:
                    generate_error_message()

            status.finish(thread_id)

        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads, thread_name_prefix="T") as ex:
                list(ex.map(download, files))
        else:
            for file in files:
                download(file)

    @staticmethod
    @on_kill(2)
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


pre_status = InfoStatus()
status: Optional[DownloadStatus] = None
downloading_files: Optional[List[MediaContainer]] = None
