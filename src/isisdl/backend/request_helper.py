from __future__ import annotations

import os
import re
import sys
import time
from base64 import standard_b64decode
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from itertools import repeat
from pathlib import Path
from threading import Thread, Lock, current_thread
from typing import Optional, Dict, List, Any, cast, Union, Iterable, DefaultDict
from urllib.parse import urlparse

from requests import Session, Response
from requests.exceptions import InvalidSchema

from isisdl.backend.crypt import get_credentials
from isisdl.backend.status import StatusOptions, DownloadStatus, RequestHelperStatus
from isisdl.settings import download_timeout, download_timeout_multiplier, download_static_sleep_time, num_tries_download
from isisdl.settings import enable_multithread, extern_discover_num_threads, is_windows, is_testing, testing_bad_urls, url_finder, isis_ignore
from isisdl.utils import User, path, sanitize_name, args, on_kill, database_helper, config, generate_error_message, logger, parse_google_drive_url, get_url_from_gdrive_confirmation, \
    DownloadThrottler, MediaType
from isisdl.utils import calculate_local_checksum


class SessionWithKey(Session):
    def __init__(self, key: str, token: str):
        super().__init__()
        self.key = key
        self.token = token

    @classmethod
    def from_scratch(cls, user: User) -> Optional[SessionWithKey]:
        try:
            s = cls("", "")
            s.headers.update({"User-Agent": "isisdl (Python Requests)"})

            s.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")
            s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s1",
                   data={
                       "shib_idp_ls_exception.shib_idp_session_ss": "",
                       "shib_idp_ls_success.shib_idp_session_ss": "false",
                       "shib_idp_ls_value.shib_idp_session_ss": "",
                       "shib_idp_ls_exception.shib_idp_persistent_ss": "",
                       "shib_idp_ls_success.shib_idp_persistent_ss": "false",
                       "shib_idp_ls_value.shib_idp_persistent_ss": "",
                       "shib_idp_ls_supported": "", "_eventId_proceed": "",
                   })

            response = s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
                              params={"j_username": user.username, "j_password": user.password, "_eventId_proceed": ""})

            if response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
                # The redirection did not work → credentials are wrong
                return None

            # Extract the session key
            _key = re.findall(r"\"sesskey\":\"(.*?)\"", response.text)
            if not _key:
                return None

            key = _key[0]

            try:
                # This is a somewhat dirty hack.
                # The Moodle API always wants to have a token. This is obtained through the `/login/token.php` site.
                # Since ISIS handles authentication via SSO, the entered password is invalid every time.

                # In [1] this way of obtaining the token is described.
                # I would love to get a better way working, but unfortunately it seems as if it is not supported.
                #
                # [1]: https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Obtain-a-Token#get-a-token-with-sso-login

                s.get("https://isis.tu-berlin.de/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledownloader")
                raise InvalidSchema
            except InvalidSchema as ex:
                token = standard_b64decode(str(ex).split("token=")[-1]).decode().split(":::")[1]

            s.key = key
            s.token = token

            return s

        except Exception as ex:
            generate_error_message(ex)

    @staticmethod
    def _timeouter(func: Any, *args: Iterable[Any], **kwargs: Dict[Any, Any]) -> Any:
        if "tubcloud.tu-berlin.de" in args[0]:
            # The tubcloud is *really* slow
            _download_timeout = 20
        else:
            _download_timeout = download_timeout

        i = 0
        while i < num_tries_download:
            try:
                return func(*args, timeout=_download_timeout + download_timeout_multiplier ** (0.5 * i), **kwargs)

            except Exception:
                time.sleep(download_static_sleep_time)
                i += 1

    def get_(self, *args: Any, **kwargs: Any) -> Optional[Response]:
        return cast(Optional[Response], self._timeouter(super().get, *args, **kwargs))

    def post_(self, *args: Any, **kwargs: Any) -> Optional[Response]:
        return cast(Optional[Response], self._timeouter(super().post, *args, **kwargs))

    def head_(self, *args: Any, **kwargs: Any) -> Optional[Response]:
        return cast(Optional[Response], self._timeouter(super().head, *args, **kwargs))

    def __str__(self) -> str:
        return "~Session~"

    def __repr__(self) -> str:
        return "~Session~"


class PreMediaContainer:
    url: str
    _name: Optional[str]
    time: Optional[int]
    size: Optional[int]
    course: Course
    media_type: MediaType
    is_cached: bool
    parent_path: Path

    def __init__(self, url: str, course: Course, media_type: MediaType, name: Optional[str] = None, relative_location: Optional[str] = None, size: Optional[int] = None, time: Optional[int] = None):
        relative_location = (relative_location or "").strip("/")
        if config.make_subdirs is False:
            relative_location = ""

        if url.endswith("?forcedownload=1"):
            url = url[:-len("?forcedownload=1")]

        self.url = url
        self._name = name
        self.time = time
        self.size = size
        self.course = course
        self.media_type = media_type
        self.is_cached = url in database_helper.get_bad_urls() or database_helper.get_pre_container_by_url(url) is not None
        self.parent_path = course.path(sanitize_name(relative_location))
        self.parent_path.mkdir(exist_ok=True)

    def __repr__(self) -> str:
        return f"{self._name}: {self.course}"


@dataclass
class MediaContainer:
    _name: str
    url: str
    download_url: str
    path: Path
    time: int
    course: Course
    media_type: MediaType
    size: int
    checksum: Optional[str] = None
    current_size: Optional[int] = None
    _stop: bool = False
    _link: Optional[MediaContainer] = None

    @classmethod
    def from_dump(cls, url: str) -> Union[bool, MediaContainer]:
        """
        The `bool` return value indicates if the container should be downloaded.
        """
        if url in database_helper.get_bad_urls():
            return False

        info = database_helper.get_pre_container_by_url(url)
        if info is None:
            return True

        container = cls(*info)
        container.media_type = MediaType(container.media_type)
        container.path = Path(container.path)

        course_id: int = container.course  # type: ignore
        container.course = RequestHelper.course_id_mapping[course_id]

        return container

    @classmethod
    def from_pre_container(cls, container: PreMediaContainer, session: SessionWithKey, status: Optional[RequestHelperStatus] = None) -> Optional[MediaContainer]:
        try:
            if is_testing and container.url in testing_bad_urls:
                return None

            maybe_container = MediaContainer.from_dump(container.url)
            if isinstance(maybe_container, MediaContainer):
                return maybe_container

            elif maybe_container is False:
                return None

            # If there was not enough information to determine name, size and time for the container, get it.
            download_url = None
            if "tu-berlin.hosted.exlibrisgroup.com" in container.url:
                pass

            elif "https://drive.google.com/" in container.url:
                drive_id = parse_google_drive_url(container.url)
                if drive_id is None:
                    return None

                temp_url = "https://drive.google.com/uc?id={id}".format(id=drive_id)

                try:
                    con = session.get_(temp_url, stream=True)
                    if con is None:
                        raise ValueError
                except Exception:
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

            elif "tubcloud.tu-berlin.de" in container.url:
                if container.url.endswith("/download"):
                    download_url = container.url
                else:
                    download_url = container.url + "/download"

            con = session.get_(download_url or container.url, params={"token": session.token}, stream=True)
            if con is None:
                database_helper.add_bad_url(container.url)
                return None

            media_type = container.media_type
            if not (con.ok and "Content-Type" in con.headers and (con.headers["Content-Type"].startswith("application/") or con.headers["Content-Type"].startswith("video/"))):
                media_type = MediaType.corrupted

            if container._name is not None and container.time is not None and container.size is not None:
                return cls(container._name, container.url, container.url, container.parent_path.joinpath(sanitize_name(container._name)),
                           container.time, container.course, media_type, container.size if media_type != MediaType.corrupted else 0).dump()

            if container._name is not None:
                name = container._name
            else:
                if maybe_names := re.findall("filename=\"(.*?)\"", str(con.headers)):
                    name = maybe_names[0]
                else:
                    name = os.path.basename(container.url)

            if media_type == MediaType.corrupted:
                size = 0
            elif container.size is not None:
                size = container.size
            else:
                if "Content-Length" not in con.headers:
                    size = -1
                    media_type = MediaType.corrupted
                else:
                    size = int(con.headers["Content-Length"])

            if container.time is not None:
                time = container.time
            elif "Last-Modified" in con.headers:
                time = int(parsedate_to_datetime(con.headers["Last-Modified"]).timestamp())
            else:
                time = int(datetime.now().timestamp())

            if not (con.ok and "Content-Type" in con.headers and (con.headers["Content-Type"].startswith("application/") or con.headers["Content-Type"].startswith("video/"))):
                media_type = MediaType.corrupted

            con.close()

            return cls(name, container.url, download_url or container.url, container.parent_path.joinpath(sanitize_name(name)), time, container.course, media_type, size).dump()

        finally:
            container.is_cached = True
            if status is not None and status.status == StatusOptions.building_cache:
                status.done()

    @property
    def should_download(self) -> bool:
        if self.media_type == MediaType.corrupted:
            assert self.size == 0
            return False

        if not self.path.exists():
            return True

        # TODO: Remove
        assert self.size != 0
        assert self.size != -1

        # TODO: This could bite me in the ass if the stat-ed size is different from the actual (gzip)
        if self.path.stat().st_size != self.size:
            return True

        maybe_container = MediaContainer.from_dump(self.url)
        if isinstance(maybe_container, bool):
            return maybe_container

        return maybe_container.checksum is None

    def dump(self) -> MediaContainer:
        database_helper.add_pre_container(self)
        return self

    def __str__(self) -> str:
        if config.absolute_path_filename:
            return str(self.path)

        return sanitize_name(self._name)

    def __repr__(self) -> str:
        return self.__str__()

    def __hash__(self) -> int:
        return self.url.__hash__()

    def __eq__(self, other: Any) -> bool:
        if self.__class__ != other.__class__:
            return False

        acc = True
        for attr in self.__dict__:
            if attr in {"current_size", "_link"}:
                continue

            self_val = getattr(self, attr)
            other_val = getattr(other, attr)

            acc &= self_val == other_val and type(self_val) == type(other_val)

        return acc

    def __gt__(self, other: MediaContainer) -> bool:
        return int.__gt__(self.size, other.size)

    def stop(self) -> None:
        self._stop = True

    def download(self, throttler: DownloadThrottler, session: SessionWithKey, is_stream: bool = False) -> None:
        # TODO: Add option to ignore corrupted and still download it.
        if self._stop or self.media_type == MediaType.corrupted or self._link is not None and self._link.media_type == MediaType.corrupted:
            return

        if self.current_size is not None:
            # assert self.current_size == self.size  # TODO
            return

        self.current_size = 0
        if self._link is not None:
            if not self._link.path.exists():
                self._link.download(throttler, session, is_stream)

            self.path.unlink(missing_ok=True)
            os.link(self._link.path, self.path)

            self.current_size = self._link.current_size
            self.checksum = calculate_local_checksum(self.path)
            self.dump()
            return

        if not self.should_download:
            self.current_size = self.size
            return

        if is_stream:
            throttler.start_stream(self.path)

        download = session.get_(self.download_url, params={"token": session.token}, stream=True)

        if download is None or not download.ok:
            self.current_size = self.size
            return

        # We copy in chunks so the download rate can be limited. This could also be done with `shutil.copyfileobj(…)`
        with self.path.open("wb") as f:
            while True:
                token = throttler.get(self.path)

                i = 0
                while i < num_tries_download:
                    try:
                        new = download.raw.read(token.num_bytes, decode_content=True)
                        break

                    except Exception:
                        i += 1

                if not new:
                    # No file left
                    break

                f.write(new)
                self.current_size += len(new)

        if is_stream:
            throttler.end_stream()

        download.close()

        # Only register the file after successfully downloading it.
        if self.size != 0 and self.size != -1:
            assert self.path.stat().st_size == self.size == self.current_size

        self.checksum = calculate_local_checksum(self.path)
        self.dump()


@dataclass
class Course:
    old_name: str
    _name: str
    name: str
    course_id: int

    @classmethod
    def from_dict(cls, info: Dict[str, Any]) -> Course:
        old_name = cast(str, info["displayname"])
        _name = cast(str, info["shortname"] or info["displayname"])
        id = cast(int, info["id"])

        if config.renamed_courses is None:
            name = _name
        else:
            name = config.renamed_courses.get(id, "") or _name

        obj = cls(sanitize_name(old_name), _name, sanitize_name(name), id)
        obj.make_directories()

        return obj

    def make_directories(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(self.path(item), exist_ok=True)

    def download_videos(self, s: SessionWithKey) -> List[PreMediaContainer]:
        if config.download_videos is False:
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
        video_urls = [item["url"] for item in videos_json]
        video_names = [item["title"].strip() + item["fileext"] for item in videos_json]

        return [PreMediaContainer(url, self, MediaType.video, name) for url, name in zip(video_urls, video_names)]

    def download_documents(self, helper: RequestHelper) -> List[PreMediaContainer]:
        content = helper.post_REST("core_course_get_contents", {"courseid": self.course_id})
        if content is None:
            return []

        content = cast(List[Dict[str, Any]], content)
        all_content: List[PreMediaContainer] = []

        for week in content:
            module: Dict[str, Any]
            for module in week["modules"]:
                # Check if the description contains url's to be followed
                if "description" in module:
                    links = url_finder.findall(module["description"])
                    for link in links:
                        parse = urlparse(link)
                        if parse.scheme and parse.netloc and config.follow_links:
                            all_content.append(PreMediaContainer(link, self, MediaType.extern, None))

                if "url" not in module:
                    continue

                url: str = module["url"]
                ignore = isis_ignore.match(url)

                if ignore is not None:
                    # Blacklist hit
                    continue

                # TODO: Check if any assertions fail
                if re.match(".*mod/(?:folder|resource)/.*", url) is None:
                    # Probably the black/white- list didn't match.
                    logger.assert_fail(f"""re.match(".*mod/(?:folder|resource)/.*", url) is None\n\nCurrent url: {url}""")

                if "contents" not in module:
                    # Probably the black/white- list didn't match.
                    logger.assert_fail(f'"contents not in file\n\nCurrent url: {url}')
                    continue

                prev_len = len(all_content)
                if "contents" in module:
                    for file in module["contents"]:
                        if config.follow_links and "type" in file and file["type"] == "url":
                            # TODO: Maybe name?
                            all_content.append(PreMediaContainer(file["fileurl"], self, MediaType.extern))
                        else:
                            all_content.append(PreMediaContainer(file["fileurl"], self, MediaType.document, file["filename"], file["filepath"], file["filesize"], file["timemodified"]))

                if len(all_content) == prev_len:
                    if url not in {
                        "https://isis.tu-berlin.de/mod/folder/view.php?id=1145174",
                    }:
                        logger.assert_fail(f"url ({url}) not in known_bad_urls")

        return all_content

    def path(self, *args: str) -> Path:
        # Custom path function that prepends the args with the course name.
        return path(self.name, *args)

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
    _courses: List[Course]
    _meta_info: Dict[str, str]
    course_id_mapping: Dict[int, Course] = {}
    _instance: Optional[RequestHelper] = None
    _instance_init: bool = False

    def __init__(self, user: User, status: Optional[RequestHelperStatus] = None):
        if self._instance_init:
            return

        if status is not None:
            status.set_status(StatusOptions.authenticating)

        self.user = user
        session = SessionWithKey.from_scratch(self.user)

        if session is None:
            print(f"I had a problem getting the user {self.user}. You have probably entered the wrong credentials.\nBailing out…")
            os._exit(1)

        self.session = session
        self._meta_info = cast(Dict[str, str], self.post_REST("core_webservice_get_site_info"))
        self.get_courses()

        RequestHelper._instance_init = True

    def __new__(cls, user: User, status: Optional[RequestHelperStatus] = None) -> RequestHelper:
        if RequestHelper._instance is None:
            RequestHelper._instance = super().__new__(cls)

        return RequestHelper._instance

    def get_courses(self) -> None:
        courses = cast(List[Dict[str, str]], self.post_REST("core_enrol_get_users_courses", {"userid": self._meta_info["userid"]}))
        self.courses = []
        self._courses = []

        for _course in courses:
            course = Course.from_dict(_course)
            RequestHelper.course_id_mapping.update({course.course_id: course})

            self._courses.append(course)
            if course.ok:
                self.courses.append(course)

        self._courses = sorted(self._courses)
        self.courses = sorted(self.courses)

    def make_course_paths(self) -> None:
        for course in self.courses:
            course.make_directories()

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

    def download_content(self, status: Optional[RequestHelperStatus] = None) -> Dict[MediaType, List[MediaContainer]]:
        """
        The main download routine. You always call this one.
        """
        exception_lock = Lock()

        if status is not None:
            status.set_status(StatusOptions.getting_content)
            status.set_total(len(self.courses) + 2)

        # TODO: Benchmark on how to make this faster
        if enable_multithread:
            with ThreadPoolExecutor(len(self.courses)) as ex:
                _pre_containers = list(ex.map(self._download_course, self.courses, repeat(exception_lock), repeat(status)))
        else:
            _pre_containers = [self._download_course(course, exception_lock, status) for course in self.courses]

        pre_containers = [item for row in _pre_containers for item in row]
        pre_containers.extend(self._download_mod_assign())

        if status is not None:
            status.set_total(len(pre_containers))
            status.set_build_cache_files(pre_containers)

            if sum(1 for pre_container in pre_containers if not pre_container.is_cached):
                status.set_status(StatusOptions.building_cache)

        # Now build the MediaContainers
        if enable_multithread:
            with ThreadPoolExecutor(extern_discover_num_threads) as ex:
                _containers = list(ex.map(MediaContainer.from_pre_container, pre_containers, repeat(self.session), repeat(status)))
        else:
            _containers = [MediaContainer.from_pre_container(pre_container, self.session, status) for pre_container in pre_containers]

        containers = check_for_conflicts_in_files([item for item in _containers if item is not None])
        mapping: Dict[MediaType, List[MediaContainer]] = {typ: [] for typ in MediaType}

        for container in containers:
            mapping[container.media_type].append(container)

        return {typ: sorted(item, key=lambda x: x.time, reverse=True) for typ, item in mapping.items()}

    def _download_mod_assign(self) -> List[PreMediaContainer]:
        all_content = []
        _assignments = self.post_REST('mod_assign_get_assignments')
        if _assignments is None:
            return []

        assignments = cast(Dict[str, Any], _assignments)

        allowed_ids = {item.course_id for item in self.courses}
        for _course in assignments["courses"]:
            if _course["id"] in allowed_ids:
                for assignment in _course["assignments"]:
                    for file in assignment["introattachments"]:
                        file["filepath"] = assignment["name"]
                        all_content.append(PreMediaContainer(file["fileurl"], RequestHelper.course_id_mapping[_course["id"]], MediaType.document,
                                                             file["filename"], file["filepath"], file["filesize"], file["timemodified"]))

        return all_content

    def _download_course(self, course: Course, exception_lock: Lock, status: Optional[RequestHelperStatus] = None) -> List[PreMediaContainer]:
        try:
            return course.download_videos(self.session) + course.download_documents(self)

        except Exception as ex:
            with exception_lock:
                generate_error_message(ex)

        finally:
            if status is not None:
                status.done()


def check_for_conflicts_in_files(files: List[MediaContainer]) -> List[MediaContainer]:
    final_list: List[MediaContainer] = []
    new_files: List[MediaContainer] = []

    for file in files:
        if file.media_type == MediaType.corrupted:
            final_list.append(file)
        else:
            new_files.append(file)

    files = new_files

    hard_link_conflicts: DefaultDict[str, List[MediaContainer]] = defaultdict(list)

    for file in {file.path: file for file in files}.values():
        hard_link_conflicts[f"{file.course.course_id} {file.size}"].append(file)

    new_files = []
    for _, conflict in hard_link_conflicts.items():
        if len(conflict) == 1:
            new_files.extend(conflict)
            continue

        for conf in conflict[1:]:
            conf._link = conflict[0]

        final_list.extend(conflict)

    files = new_files

    conflicts = defaultdict(list)
    for file in files:
        conflicts[file.path].append(file)

    for typ, conflict in conflicts.items():
        conflict.sort(key=lambda x: x.time)

        if len(conflict) == 1 or all(item.size == conflict[0].size for item in conflict):
            final_list.append(conflict[0])

        elif len(set(item.size for item in conflict)) == len(conflict):
            if is_testing:
                assert False

            for i, item in enumerate(conflict):
                basename, ext = os.path.splitext(item._name)
                item._name = basename + f".{i}" + ext
                final_list.append(item)

        else:
            logger.assert_fail(f"conflict: {[item.__dict__ for item in conflict]}")
            continue

    return final_list


class CourseDownloader:
    containers: Dict[MediaType, List[MediaContainer]] = {}

    def start(self) -> None:
        with RequestHelperStatus() as status:
            helper = RequestHelper(get_credentials(), status)
            containers = helper.download_content(status)

        CourseDownloader.containers = containers

        # Make the runner a thread in case of a user needing to exit the program → downloading is done in the main thread
        throttler = DownloadThrottler()
        with DownloadStatus(containers, args.num_threads, throttler) as status:
            Thread(target=self.stream_files, args=(containers, throttler, status), daemon=True).start()
            if not args.stream:
                downloader = Thread(target=self.download_files, args=(containers, throttler, helper.session, status))
                downloader.start()

            # Log the metadata
            conf = config.to_dict()
            del conf["password"]
            logger.post({
                "num_g_files": len(containers),
                "num_c_files": len(containers),

                "total_g_bytes": sum((item.size for row in containers.values() for item in row)),
                "total_c_bytes": sum((item.size for row in containers.values() for item in row)),

                "course_ids": sorted([course.course_id for course in helper._courses]),

                "config": conf,
            })

            if args.stream:
                while True:
                    time.sleep(65536)

            downloader.join()

    def stream_files(self, files: Dict[MediaType, List[MediaContainer]], throttler: DownloadThrottler, status: DownloadStatus) -> None:
        if is_windows:
            return

        # return

        if sys.version_info >= (3, 10):
            # TODO: Figure out how to support python3.10
            return

        else:
            import pyinotify

            class EventHandler(pyinotify.ProcessEvent):  # type: ignore[misc]
                def __init__(self, files: List[MediaContainer], throttler: DownloadThrottler, **kwargs: Any):
                    self.files: Dict[Path, MediaContainer] = {file.path: file for file in files}
                    self.throttler = throttler
                    super().__init__(**kwargs)

                # TODO: Also watch for close events and end the stream
                def process_IN_OPEN(self, event: pyinotify.Event) -> None:
                    if event.dir:
                        return

                    file = self.files.get(event.pathname, None)
                    if file is not None and file.current_size is not None:
                        return

                    if file is None:
                        return

                    if file.current_size is not None:
                        return

                    status.add_streaming(file)
                    file.download(self.throttler, SessionWithKey("uwu", "owo"), True)  # TODO
                    status.done_streaming()

            wm = pyinotify.WatchManager()
            notifier = pyinotify.Notifier(wm, EventHandler([item for row in files.values() for item in row], throttler))
            wm.add_watch(str(path()), pyinotify.ALL_EVENTS, rec=True, auto_add=True)

            notifier.loop()

    def download_files(self, files: Dict[MediaType, List[MediaContainer]], throttler: DownloadThrottler, session: SessionWithKey, status: DownloadStatus) -> None:
        # TODO: Dynamic calculation of num threads such that optimal Internet Usage is achieved
        exception_lock = Lock()

        def download(file: MediaContainer) -> None:
            if enable_multithread:
                thread_id = int(current_thread().name.split("T_")[-1])
            else:
                thread_id = 0

            status.add_container(thread_id, file)
            try:
                file.download(throttler, session)
                status.done(thread_id, file)

            except Exception as ex:
                with exception_lock:
                    generate_error_message(ex)

        first_files: List[MediaContainer] = []
        second_files: List[MediaContainer] = []

        for _files in files.values():
            for file in _files:
                if not file.should_download:
                    first_files.append(file)
                else:
                    second_files.append(file)

        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads, thread_name_prefix="T") as ex:
                list(ex.map(download, first_files + second_files))
        else:
            for file in first_files + second_files:
                download(file)

        print()

    @staticmethod
    @on_kill(2)
    def shutdown_running_downloads(*_: Any) -> None:
        if not CourseDownloader.containers:
            return

        if args.stream:
            return

        for row in CourseDownloader.containers.values():
            for item in row:
                item.stop()

        # Now wait for the downloads to finish
        while not all(item.current_size is not None or item.current_size != item.size for row in CourseDownloader.containers.values() for item in row):
            time.sleep(0.25)
