from __future__ import annotations

import os
import re
import sys
import time
from base64 import standard_b64decode
from collections import defaultdict, namedtuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Thread, Lock, current_thread
from typing import Optional, Dict, List, Any, cast, Tuple, Set, Union, Iterable
from urllib.parse import urlparse

from isisdl.backend.crypt import get_credentials
from isisdl.backend.status import StatusOptions, DownloadStatus, RequestHelperStatus
from isisdl.utils import User, path, sanitize_name, args, on_kill, database_helper, config, generate_error_message, logger, parse_google_drive_url, get_url_from_gdrive_confirmation, bad_urls, \
    DownloadThrottler, MediaType
from isisdl.settings import enable_multithread, extern_discover_num_threads, is_windows, is_testing, _testing_bad_urls

from requests import Session, Response
from requests.exceptions import InvalidSchema

from src.isisdl.settings import error_text, download_timeout, download_timeout_multiplier, sleep_time_for_isis, num_tries_download
from src.isisdl.utils import calculate_local_checksum

# TODO: is_cached as attribute of ExternalLink
ExternalLink = namedtuple("ExternalLink", "url course media_type name")
external_links: Set[ExternalLink] = set()
num_uncached_external_links = 0

# Regex copied from https://gist.github.com/gruber/8891611
url_finder = re.compile(r"""(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.]
(?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br
|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk
|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne
|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr
|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)/)
(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.]
(?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs
|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm
|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf
|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt
|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))""")

# TODO: Get rid of these / factor them into one big blob
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
            # TODO: regex match this
            key = response.text.split("https://isis.tu-berlin.de/login/logout.php?sesskey=")[-1].split("\"")[0]

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
            print(f"{error_text} I was unable to establish a connection.\n\nReason: {ex}\n\nBailing out!")
            os._exit(1)

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
                time.sleep(sleep_time_for_isis)
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

    @classmethod
    def from_dump(cls, url: str) -> Union[bool, MediaContainer]:
        """
        A return value of True indicates that the container does not exist, but should be downloaded.
        A return value of False indicates that the container does not exist and should not be downloaded.
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

    # TODO: Add the verification also for Documents + if status code != 200: corrupted
    @classmethod
    def from_extern_link(cls, url: str, course: Course, session: SessionWithKey, media_type: MediaType, filename: Optional[str] = None) -> Optional[MediaContainer]:
        container = cls.from_dump(url)
        if container is False:
            return None

        if isinstance(container, MediaContainer):
            return container

        if isis_ignored.match(url):
            database_helper.add_bad_url(url)
            return None

        # Now check if some things like authentication / form post have to be done
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

            location = course.path(sanitize_name(relative_location), sanitize_name(name))

            if "" in con.headers:
                time = int(parsedate_to_datetime(con.headers["Last-Modified"]).timestamp())
            else:
                time = int(datetime.now().timestamp())

            if download_url.endswith("?forcedownload=1"):
                download_url = download_url[:-len("?forcedownload=1")]

            container = MediaContainer(name, url, download_url, location, time, course, media_type, size)

        else:
            database_helper.add_bad_url(url)
            if url not in known_bad_extern_urls:
                logger.message(f"Assertion failed: url not ignored: {url}")

        con.close()
        if isinstance(container, MediaContainer):
            container.dump()
            return container

            # An attempt at making streaming more transparent. The metadata of mp4 files is located at the beginning / end.
            # If we download both at the startup, then vlc *should* just assume they are normal files.
            # This, unfortunately does not work this way.
            # TODO: Figure out why

            # if container.media_type == MediaType.video:
            #     with open(container.path, "wb") as f:
            #         start_of_file = con.raw.read(video_discover_download_size, decode_content=True)
            #         end_of_file = session.get(download_url, headers={"Range": f"bytes={container.size - video_discover_download_size}-{container.size}"}).content
            #         f.write(start_of_file)
            #         f.seek(container.size - len(end_of_file), 0)
            #         f.write(end_of_file)

        return None

    @classmethod
    def document_from_api(cls, name: str, url: str, download_url: str, course: Course, last_modified: int, relative_location: Optional[str] = "", size: int = -1) -> MediaContainer:
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

        location = course.path(sanitize_name(relative_location), sanitize_name(name))

        if "webservice/pluginfile.php" not in url and "mod/videoservice/file.php" not in url:
            logger.message("""Assertion failed: "webservice/pluginfile.php" not in url and "mod/videoservice/file.php" not in url""")
            pass

        return cls(name, url, download_url, location, last_modified, course, MediaType.document, size)

    @property
    def should_download(self) -> bool:
        if self.media_type == MediaType.corrupted:
            return False

        assert self.size != 0
        assert self.size != -1

        if os.stat(self.path).st_size != self.size:
            return True

        maybe_container = MediaContainer.from_dump(self.url)
        if isinstance(maybe_container, bool):
            return maybe_container

        if maybe_container.checksum is None:
            return True

        if maybe_container.checksum != calculate_local_checksum(Path(self.path)):
            return True

        return False

    def check_is_corrupted(self) -> bool:
        pass

    def dump(self) -> None:
        database_helper.add_pre_container(self)

    def __str__(self) -> str:
        return sanitize_name(self._name)

    def __repr__(self) -> str:
        return self.__str__()

    def __hash__(self) -> int:
        return self.url.__hash__()

    def __eq__(self, other: Any) -> bool:
        return self.__class__ == other.__class__ and all(getattr(self, item) == getattr(other, item) for item in self.__dict__ if item != "current_size")

    def stop(self) -> None:
        self._stop = True

    def download(self, throttler: DownloadThrottler, session: SessionWithKey, is_stream: bool = False) -> None:
        if self.current_size is not None:
            # assert self.current_size == self.size  # TODO
            return

        self.current_size = 0

        if is_stream:
            throttler.start_stream(self.path)

        download = session.get_(self.download_url, params={"token": session.token}, stream=True)

        if download is None or not download.ok:
            self.current_size = self.size
            return

        # We copy in chunks to add the rate limiter and status indicator.
        # This could also be done with `shutil.copyfileobj(…)`, but, with this approach, the download rate can be limited.
        with open(self.path, "wb") as f:
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
        assert self.path.stat().st_size == self.size == self.current_size

        self.checksum = calculate_local_checksum(Path(self.path))
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

        external_links.update({ExternalLink(item, self, MediaType.video, name) for item, name in zip(video_urls, video_names)})

    def download_documents(self, helper: RequestHelper) -> List[MediaContainer]:
        content = helper.post_REST("core_course_get_contents", {"courseid": self.course_id})
        if content is None:
            return []

        content = cast(List[Dict[str, Any]], content)
        all_content: List[MediaContainer] = []

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
                            external_links.add(ExternalLink(link, self, MediaType.extern, None))

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
                            external_links.add(ExternalLink(file["fileurl"], self, MediaType.extern, None))
                        elif file["fileurl"] in bad_urls:
                            pass
                        else:
                            all_content.append(MediaContainer.document_from_api(file["filename"], file["fileurl"], file["fileurl"], self, file["timemodified"], file["filepath"], file["filesize"]))

                if len(all_content) == prev_len:

                    if url not in known_bad_isis_urls:
                        logger.message("""Assertion failed: url not in known_bad_urls""")
                        pass

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
            exit(1)

        self.session = session
        self._courses = []
        self.courses = []

        self._meta_info = cast(Dict[str, str], self.post_REST("core_webservice_get_site_info"))
        self.get_courses()

        RequestHelper._instance_init = True

    def __new__(cls, user: User, status: Optional[RequestHelperStatus] = None) -> RequestHelper:
        if RequestHelper._instance is None:
            RequestHelper._instance = super().__new__(cls)

        return RequestHelper._instance

    def get_courses(self) -> None:
        res = cast(List[Dict[str, str]], self.post_REST("core_enrol_get_users_courses", {"userid": self.userid}))
        self.courses = []
        self._courses = []

        for item in res:
            course = Course.from_dict(item)
            RequestHelper.course_id_mapping.update({course.course_id: course})

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

    def make_course_paths(self) -> None:
        for course in self.courses:
            if not os.path.exists(course.path()):
                os.makedirs(course.path(), exist_ok=True)
            course.make_directories()

    def download_content(self, status: Optional[RequestHelperStatus] = None) -> List[MediaContainer]:
        """
        Attention: This method does *not* take into account file conflicts.
        You will have to resolve them again by calling `check_for_conflicts_in_files(containers)`
        """
        global num_uncached_external_links
        exception_lock = Lock()

        if status is not None:
            status.set_status(StatusOptions.getting_content)

        # The number of threads that are going to spawn
        if status is not None:
            status.set_total(len(self.courses) + 1)

        def download_documents(course: Course) -> List[MediaContainer]:
            try:
                course.download_videos(self.session)
                ret = course.download_documents(self)
                if status is not None:
                    status.done()

                return ret

            except Exception as ex:
                with exception_lock:
                    generate_error_message(ex)
                    return []

        def download_mod_assign(ret: List[MediaContainer]) -> None:
            try:
                ret.extend(self.download_mod_assign())
                if status is not None:
                    status.done()

            except Exception as ex:
                with exception_lock:
                    generate_error_message(ex)

        if enable_multithread:
            mod_assign: List[MediaContainer] = []
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

        if external_links:
            if status is not None:
                status.set_status(StatusOptions.getting_extern)
                status.set_total(len(external_links))

        extern = self.download_extern(status)

        videos = []
        for thing in extern:
            if thing.media_type == MediaType.video:
                videos.append(thing)
            else:
                documents.append(thing)

        all_files = [item for item in documents + mod_assign + videos if item.url not in _testing_bad_urls]
        all_files = check_for_conflicts_in_files(all_files)

        documents, extern, videos = [], [], []
        for container in all_files:
            if container.media_type == MediaType.document:
                documents.append(container)
            elif container.media_type == MediaType.extern:
                extern.append(container)
            elif container.media_type == MediaType.video:
                videos.append(container)
            elif container.media_type == MediaType.corrupted:
                pass
            else:
                assert False

        # Download the newest files first
        def sort(lst: List[MediaContainer]) -> List[MediaContainer]:
            return sorted(lst, key=lambda x: x.time, reverse=True)

        return sort(documents) + sort(extern) + sort(videos)

    def download_mod_assign(self) -> List[MediaContainer]:
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
                        all_content.append(MediaContainer.document_from_api(file["filename"], file["fileurl"], file["fileurl"], course, file["timemodified"], file["filepath"], file["filesize"]))

        return all_content

    def download_extern(self, status: Optional[RequestHelperStatus]) -> List[MediaContainer]:
        all_content = []

        def add_extern_link(extern: ExternalLink) -> None:
            container = MediaContainer.from_extern_link(extern.url, extern.course, self.session, extern.media_type, extern.name)
            if container is not None:
                all_content.append(container)

            if status is not None and status.status == StatusOptions.getting_extern:
                status.done()

        if external_links:
            if enable_multithread:
                with ThreadPoolExecutor(extern_discover_num_threads) as ex:
                    list(ex.map(add_extern_link, external_links))
            else:
                for link in external_links:
                    add_extern_link(link)

        return all_content

    @property
    def userid(self) -> str:
        return self._meta_info["userid"]


# TODO: Resolve conflicts by hard links
# TODO: check if testing and maybe exclude links here
# TODO: Return dict based on MediaTypes?
def check_for_conflicts_in_files(files: List[MediaContainer]) -> List[MediaContainer]:
    content: List[MediaContainer] = []
    conflicts = defaultdict(list)

    for item in set(files):
        conflicts[item.path].append(item)

    for conflict in conflicts.values():
        conflict.sort(key=lambda x: x.time)

        if len(conflict) == 1 or all(item.size == conflict[0].size for item in conflict):
            content.append(conflict[0])

        elif len(set(item.size for item in conflict)) == len(conflict):
            if is_testing:
                assert False

            for i, item in enumerate(conflict):
                basename, ext = os.path.splitext(item._name)
                item._name = basename + f".{i}" + ext
                content.append(item)

        else:
            logger.message(f"Assertion failed: conflict: {[item.__dict__ for item in conflict]}")
            continue

    return content


class CourseDownloader:
    containers: List[MediaContainer] = []

    def start(self) -> None:
        with RequestHelperStatus() as status:
            helper = RequestHelper(get_credentials(), status)
            containers = helper.download_content(status)

        # Make all files so that they can be streamed
        for container in containers:
            if not os.path.exists(container.path):
                open(container.path, "w").close()

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

                "total_g_bytes": sum((item.size for item in containers)),
                "total_c_bytes": sum((item.size for item in containers)),

                "course_ids": sorted([course.course_id for course in helper._courses]),

                "config": conf,
            })

            if args.stream:
                while True:
                    time.sleep(65536)

            downloader.join()

    def stream_files(self, files: List[MediaContainer], throttler: DownloadThrottler, status: DownloadStatus) -> None:
        if is_windows:
            return

        if sys.version_info >= (3, 10):
            # TODO: Figure out how to support python3.10
            return

        else:
            import pyinotify

            class EventHandler(pyinotify.ProcessEvent):  # type: ignore
                def __init__(self, files: List[MediaContainer], throttler: DownloadThrottler, **kwargs: Any):
                    self.files: Dict[str, MediaContainer] = {file.location: file for file in files}
                    self.throttler = throttler
                    super().__init__(**kwargs)

                # TODO: Also watch for close events and end the stream
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

                    status.add_streaming(file)
                    file.download(self.throttler, True)
                    status.done_streaming()

            wm = pyinotify.WatchManager()
            notifier = pyinotify.Notifier(wm, EventHandler(files, throttler))
            wm.add_watch(path(), pyinotify.ALL_EVENTS, rec=True, auto_add=True)

            notifier.loop()

    def download_files(self, files: List[MediaContainer], throttler: DownloadThrottler, session: SessionWithKey, status: DownloadStatus) -> None:
        # TODO: Dynamic calculation of num threads such that optimal Internet Usage is achieved
        exception_lock = Lock()

        def download(file: MediaContainer) -> None:
            assert status is not None
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

        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads, thread_name_prefix="T") as ex:
                list(ex.map(download, files))
        else:
            for file in files:
                download(file)

    @staticmethod
    @on_kill(2)
    def shutdown_running_downloads(*_: Any) -> None:
        downloading_files = CourseDownloader.containers
        if not downloading_files:
            return

        if args.stream:
            return

        for item in downloading_files:
            item.stop()

        # Now wait for the downloads to finish
        while not all(item.current_size != item.size for item in downloading_files):
            time.sleep(0.25)
