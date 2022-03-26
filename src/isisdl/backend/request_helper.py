from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate, parsedate_to_datetime
from itertools import repeat
from threading import Thread
from typing import Optional, Dict, List, Any, cast, Tuple, Set
from urllib.parse import urlparse, urljoin

import pyinotify
import watchdog as watchdog
from pyinotify import ProcessEvent

from isisdl.backend.downloads import SessionWithKey, MediaType, MediaContainer, DownloadStatus, DownloadThrottler, InfoStatus, PreStatusInfo
from isisdl.backend.utils import User, path, sanitize_name, args, on_kill, database_helper, config, generate_error_message, logger, parse_google_drive_url, get_url_from_gdrive_confirmation
from isisdl.settings import enable_multithread, checksum_algorithm, extern_discover_num_threads, video_discover_download_size

ignored_urls = {
    "https://isis.tu-berlin.de/mod/resource/view.php?id=756880",
    "https://isis.tu-berlin.de/mod/resource/view.php?id=910864",
}

known_bad_isis_urls = {
    "https://isis.tu-berlin.de/mod/folder/view.php?id=1145174",
}

known_bad_extern_urls = {
    "https://www.sese.tu-berlin.de/kloes",
    "https://www.qemu.org/docs/master/system/index.html",
    "https://developer.arm.com/documentation/ihi0042/j/?lang=en",
    "http://infocenter.arm.com/help/topic/com.arm.doc.qrc0001m/QRC0001_UAL.pdf",
    "https://gcc.gnu.org/onlinedocs/gcc-10.2.0/gcc/",
    "https://sourceware.org/gdb/current/onlinedocs/gdb/",
    "https://elinux.org/BCM2835_datasheet_errata",
    "http://www.gnu.org/software/make/manual/make.html",
    "http://de.wikibooks.org/wiki/C-Programmierung",
    "http://openbook.galileocomputing.de/c_von_a_bis_z/",
    "https://www.qemu.org/",
    "https://sourceware.org/binutils/docs-2.35/",
    "https://developer.arm.com/documentation/ddi0406/latest",
}

external_links: Set[Tuple[str, Course, MediaType, Optional[str]]] = set()
num_uncached_external_links = 0

# Regex copied from https://gist.github.com/gruber/8891611
url_finder = re.compile(
    r"""(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)/)(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))""")

isis_ignored = re.compile(
    ".*(?:"
    # Ignore mod/{whatever}
    "mod/(?:"
    "forum|choicegroup|assign|feedback|choice|quiz|glossary|questionnaire|scorm|etherpadlite|lti|h5pactivity|"
    "page|data|ratingallocate|book"
    ")"
    # Ignore other websites
    "|tu-berlin.zoom.us"
    "|arm.com/products"
    ")/.*")


@dataclass
class PreMediaContainer:
    _name: str
    url: str
    download_url: str
    location: str
    time: int
    course_id: int
    media_type: MediaType
    size: int = -1
    checksum: Optional[str] = None

    @classmethod
    def from_dump(cls, url: str) -> Optional[PreMediaContainer]:
        info = database_helper.get_pre_container_by_url(url)
        if info is None:
            return None

        container = cls(*info)
        container.media_type = MediaType(container.media_type)

        return container

    @classmethod
    def from_extern_link(cls, url: str, course: Course, session: SessionWithKey, media_type: MediaType, filename: Optional[str] = None) -> Optional[PreMediaContainer]:
        # Use the cache
        if url in database_helper.get_bad_urls():
            return None

        container = cls.from_dump(url)
        if container is not None:
            return container

        # Now check if some things like authentication / form post have to be done
        if isis_ignored.match(url):
            database_helper.add_bad_url(url)
            return None

        download_url = ""
        if "tu-berlin.hosted.exlibrisgroup.com" in url:
            pass

        elif "https://drive.google.com/" in url:
            # page = session.get_(url)
            drive_id = parse_google_drive_url(url)
            if drive_id is None:
                return None

            temp_url = "https://drive.google.com/uc?id={id}".format(id=drive_id)

            try:
                con = session.get_(temp_url, stream=True)
            except Exception:
                return None

            if con is None:
                return None

            if "Content-Disposition" in con.headers:
                # This is the file
                download_url = temp_url
            else:
                _url = get_url_from_gdrive_confirmation(con.text)
                if _url is None:
                    return None
                download_url = _url

            con.close()

        elif "tubcloud.tu-berlin.de" in url:
            if url.endswith("/download"):
                download_url = url
            else:
                download_url = url + "/download"

        try:
            con = session.get_(download_url or url, stream=True)
        except Exception:
            return None

        if con is None:
            database_helper.add_bad_url(url)
            return None

        if download_url == "":
            download_url = url

        if "Content-Type" in con.headers and (con.headers["Content-Type"].startswith("application/") or con.headers["Content-Type"].startswith("video/")):
            if filename is not None:
                name = filename
            else:
                maybe_names = re.findall("filename=\"(.*?)\"", str(con.headers))
                if maybe_names:
                    name = maybe_names[0]
                else:
                    name = os.path.basename(url)

            size = int(con.headers["Content-Length"])
            relative_location = media_type.dir_name

            location = course.path(sanitize_name(relative_location))

            if "" in con.headers:
                time = int(parsedate_to_datetime(con.headers["Last-Modified"]).timestamp())
            else:
                time = int(datetime.now().timestamp())

            container = PreMediaContainer(name, url, download_url, location, time, course.course_id, media_type, size)

        else:
            database_helper.add_bad_url(url)
            if url not in known_bad_extern_urls:
                logger.message(f"Assertion failed: url not ignored: {url}")

        if container is not None:
            container.dump()

        con.close()
        return container

    @classmethod
    def document_from_api(cls, name: str, url: str, download_url: str, course: Course, last_modified: int, relative_location: Optional[str] = "", size: int = -1) -> PreMediaContainer:
        # Sanitize bad names
        relative_location = relative_location or ""
        relative_location = relative_location.strip("/")
        if config.make_subdirs is False:
            relative_location = ""

        if relative_location:
            if database_helper.get_checksum_from_url(url) is None:
                os.makedirs(course.path(sanitize_name(relative_location)), exist_ok=True)

        is_video = "mod/videoservice/file.php" in url
        if is_video:
            relative_location = os.path.join(relative_location, "Videos")

        if url.endswith("?forcedownload=1"):
            url = url[:-len("?forcedownload=1")]

        location = course.path(sanitize_name(relative_location))

        if "webservice/pluginfile.php" not in url and "mod/videoservice/file.php" not in url:
            logger.message("""Assertion failed: "webservice/pluginfile.php" not in url and "mod/videoservice/file.php" not in url""")
            pass

        return cls(name, url, download_url, location, last_modified, course.course_id, MediaType.document, size)

    @property
    def path(self) -> str:
        return os.path.join(self.location, sanitize_name(self._name))

    def dump(self) -> None:
        database_helper.add_pre_container(self)

    def __str__(self) -> str:
        return sanitize_name(self._name)

    def __repr__(self) -> str:
        return self.__str__()

    def __hash__(self) -> int:
        return self.url.__hash__()


@dataclass
class Course:
    _name: str
    name: str
    course_id: int

    @classmethod
    def from_dict(cls, info: Dict[str, Any]) -> Course:
        _name = cast(str, info["displayname"])
        id = cast(int, info["id"])

        if config.renamed_courses is None:
            name = _name
        else:
            name = config.renamed_courses.get(id, "") or _name

        obj = cls(_name, name, id)

        for item in MediaType.list_dirs():
            os.makedirs(obj.path(item), exist_ok=True)

        return obj

    def download_videos(self, s: SessionWithKey) -> None:
        if config.download_videos is False:
            return

        url = "https://isis.tu-berlin.de/lib/ajax/service.php"
        # Thank you isia-tub for this data <3
        video_data = [{
            "index": 0,
            "methodname": "mod_videoservice_get_videos",
            "args": {"coursemoduleid": 0, "courseid": self.course_id}
        }]

        videos_res = s.get_(url, params={"sesskey": s.key}, json=video_data)
        if videos_res is None:
            return

        videos_json = videos_res.json()[0]

        if videos_json["error"]:
            return

        videos_json = videos_json["data"]["videos"]
        video_urls = [item["url"] for item in videos_json]
        video_names = [item["title"].strip() + item["fileext"] for item in videos_json]

        external_links.update({(item, self, MediaType.video, name) for item, name in zip(video_urls, video_names)})

    def download_documents(self, helper: RequestHelper) -> List[PreMediaContainer]:
        content = helper.post_REST("core_course_get_contents", {"courseid": self.course_id})
        if content is None:
            return []

        content = cast(List[Dict[str, Any]], content)

        all_content: List[PreMediaContainer] = []
        bad_urls = database_helper.get_bad_urls()

        for week in content:
            module: Dict[str, Any]
            for module in week["modules"]:
                if "description" in module:
                    links = url_finder.findall(module["description"])
                    for link in links:
                        if link in ignored_urls or link in bad_urls:
                            continue

                        parse = urlparse(link)
                        if parse.scheme and parse.netloc and config.follow_links:
                            external_links.add((link, self, MediaType.extern, None))

                if "url" not in module:
                    continue

                url: str = module["url"]

                if url in ignored_urls or url in bad_urls:
                    continue

                ignore = isis_ignored.match(url)

                if ignore is not None:
                    # Blacklist hit
                    continue

                if re.match(".*mod/(?:folder|resource)/.*", url) is None:
                    # Probably the black/white- list didn't match.
                    logger.message(f"""Assertion failed: re.match(".*mod/(?:folder|resource)/.*", url) is None\n\nCurrent url: {url}""")
                    pass

                if "contents" not in module:
                    # Probably the black/white- list didn't match.
                    logger.message(f"""Assertion failed: "contents" not in file\n\nCurrent url: {url}""")
                    continue

                prev_len = len(all_content)
                if "contents" in module:
                    for file in module["contents"]:
                        if config.follow_links and "type" in file and file["type"] == "url":
                            external_links.add((file["fileurl"], self, MediaType.extern, None))
                        elif file["fileurl"] in bad_urls:
                            pass
                        else:
                            all_content.append(PreMediaContainer.document_from_api(file["filename"], file["fileurl"], file["fileurl"], self, file["timemodified"], file["filepath"], file["filesize"]))

                if len(all_content) == prev_len:

                    if url not in known_bad_isis_urls:
                        logger.message("""Assertion failed: url not in known_bad_urls""")
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
        return f"{self._name} ({self.course_id})"

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
        pre_status.set_status(PreStatusInfo.authenticating)
        session = SessionWithKey.from_scratch(self.user)

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

    def get_courses(self) -> None:
        res = cast(List[Dict[str, str]], self.post_REST("core_enrol_get_users_courses", {"userid": self.userid}))
        self.courses = []
        self._courses = []

        for item in res:
            course = Course.from_dict(item)
            self.course_id_mapping.update({course.course_id: course})

            self._courses.append(course)
            if course.ok:
                self.courses.append(course)

        self._courses = sorted(self._courses)
        self.courses = sorted(self.courses)

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
        global num_uncached_external_links
        exception_lock = threading.Lock()

        pre_status.set_status(PreStatusInfo.getting_content)

        # The number of threads that are going to spawn
        pre_status.set_max_content(len(self.courses) + 1)

        def download_documents(course: Course) -> List[PreMediaContainer]:
            try:
                course.download_videos(self.session)
                ret = course.download_documents(self)
                pre_status.done_thing()

                return ret

            except Exception:
                with exception_lock:
                    generate_error_message()
                    return []

        def download_mod_assign(ret: List[PreMediaContainer]) -> None:
            try:
                ret.extend(self.download_mod_assign())
                pre_status.done_thing()

            except Exception:
                with exception_lock:
                    generate_error_message()

        if enable_multithread:
            mod_assign: List[PreMediaContainer] = []
            mod_assign_thread = Thread(target=download_mod_assign, args=(mod_assign,))
            mod_assign_thread.start()

            with ThreadPoolExecutor(len(self.courses)) as ex:
                _documents = list(ex.map(download_documents, self.courses))

            mod_assign_thread.join()

        else:
            mod_assign = self.download_mod_assign()
            _documents = [course.download_documents(self) for course in self.courses]

        documents = [item for row in _documents for item in row]

        # Figure out how many urls to get
        bad_urls = database_helper.get_bad_urls()
        for item in external_links:
            if item[0] not in bad_urls and database_helper.get_pre_container_by_url(item[0]) is None:
                num_uncached_external_links += 1

        if num_uncached_external_links:
            pre_status.set_status(PreStatusInfo.getting_extern)
            pre_status.set_max_content(num_uncached_external_links)

        extern = self.download_extern()

        def sort(lst: List[PreMediaContainer]) -> List[PreMediaContainer]:
            return sorted(lst, key=lambda x: x.time, reverse=True)

        videos = []
        for thing in extern:
            if thing.media_type == MediaType.video:
                videos.append(thing)
            else:
                documents.append(thing)
        # Download the newest files first
        all_files = sort(documents + mod_assign) + sort(videos)
        check_for_conflicts_in_files(all_files)

        return all_files

    def download_mod_assign(self) -> List[PreMediaContainer]:
        all_content = []
        _assignments = self.post_REST('mod_assign_get_assignments')
        if _assignments is None:
            return []

        assignments = cast(Dict[str, Any], _assignments)

        allowed_ids = {item.course_id for item in self.courses}
        for _course in assignments["courses"]:
            course = next((item for item in self.courses if item.course_id == _course["id"]), None)
            if course is None:
                logger.message("Assertion failed: course is None")
                continue

            if _course["id"] in allowed_ids:
                for assignment in _course["assignments"]:
                    for file in assignment["introattachments"]:
                        file["filepath"] = assignment["name"]
                        all_content.append(PreMediaContainer.document_from_api(file["filename"], file["fileurl"], file["fileurl"], course, file["timemodified"], file["filepath"], file["filesize"]))

        return all_content

    def download_extern(self) -> List[PreMediaContainer]:
        all_content = []

        def add_extern_link(extern: Tuple[str, Course, MediaType, Optional[str]]) -> None:
            container = PreMediaContainer.from_extern_link(extern[0], extern[1], self.session, extern[2], extern[3])
            if container is not None:
                all_content.append(container)

            if pre_status.status == PreStatusInfo.getting_extern:
                pre_status.done_thing()

        if external_links:
            if enable_multithread:
                with ThreadPoolExecutor(extern_discover_num_threads) as ex:
                    ex.map(add_extern_link, external_links)
            else:
                for link in external_links:
                    add_extern_link(link)

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

        # Later: Server?

        for new_row in locations.values():
            for i, item in enumerate(new_row):
                basename, ext = os.path.splitext(item._name)
                item._name = basename + f".{i}" + ext


class CourseDownloader:
    helper: Optional[RequestHelper] = None

    def __init__(self, user: User):
        self.user = user

    def start(self) -> None:
        global pre_status
        pre_status = InfoStatus()
        pre_status.start()

        self.helper = RequestHelper(self.user)

        pre_containers = self.helper.download_content()
        media_containers = self.make_files(pre_containers)

        # Make all files so that they can be streamed
        for container in media_containers:
            if not os.path.exists(container.location):
                open(container.location, "w").close()

        global downloading_files
        downloading_files = media_containers

        # Make the runner a thread in case of a user needing to exit the program → downloading is done in the main thread
        global status
        throttler = DownloadThrottler()
        status = DownloadStatus(media_containers, args.num_threads, throttler)
        downloader = Thread(target=self.download_files, args=(media_containers, throttler))
        streamer = Thread(target=self.stream_files, args=(media_containers, throttler))

        pre_status.stop()
        downloader.start()
        streamer.start()
        status.start()

        # Log the metadata
        conf = config.to_dict()
        del conf["password"]
        logger.post({
            "num_g_files": len(pre_containers),
            "num_c_files": len(media_containers),

            "total_g_bytes": sum((item.size for item in pre_containers)),
            "total_c_bytes": sum((item.size for item in media_containers)),

            "course_ids": sorted([course.course_id for course in self.helper._courses]),

            "config": conf,
        })

        downloader.join()
        status.join(0)

    def make_files(self, files: List[PreMediaContainer]) -> List[MediaContainer]:
        assert self.helper is not None

        new_files = [MediaContainer.from_pre_container(file, self.helper.session) for file in files]
        filtered_files = [item for item in new_files if item is not None]

        return filtered_files

    def stream_files(self, files: List[MediaContainer], throttler: DownloadThrottler) -> None:
        class EventHandler(pyinotify.ProcessEvent):  # type: ignore
            def __init__(self, files: List[MediaContainer], throttler: DownloadThrottler, **kwargs: Any):
                self.files: Dict[str, MediaContainer] = {file.location: file for file in files}
                self.throttler = throttler
                super().__init__(**kwargs)

            def process_IN_OPEN(self, event: pyinotify.Event) -> None:
                if event.dir:
                    return

                file = self.files.get(event.pathname, None)
                if file is not None and file.curr_size is not None:
                    return

                if file is None:
                    return

                if file.curr_size is not None:
                    return

                file.download(self.throttler, True)

        wm = pyinotify.WatchManager()
        notifier = pyinotify.Notifier(wm, EventHandler(files, throttler))
        wm.add_watch(path(), pyinotify.IN_OPEN, rec=True)

        notifier.loop()

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
