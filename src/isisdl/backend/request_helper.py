from __future__ import annotations

import base64
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import repeat
from pathlib import Path
from typing import Optional, Dict, List, Iterable, Callable

import requests
from bs4 import BeautifulSoup
from requests import Session


from isisdl.backend.downloads import SessionWithKey, MediaType, MediaContainer
from isisdl.share.settings import num_sessions, download_timeout, course_name_to_id_file_location, download_dir_location
from isisdl.share.utils import logger, User, debug_time, path, sanitize_name_for_dir, args
from isisdl.backend.checksums import CheckSumHandler

@dataclass
class Course:
    name: str
    course_id: str

    @classmethod
    def from_name(cls, name: str):
        try:
            with open(path(course_name_to_id_file_location)) as f:
                the_id = json.load(f)[name]

        except (FileNotFoundError, KeyError, json.decoder.JSONDecodeError) as ex:
            logger.warning(f"I could not find the ID for course {name}. This shouldn't be a problem - just restart me when I'm done downloading the courses.")
            raise ex

        return cls(name, the_id)

    @classmethod
    def from_dict(cls, info: dict):
        return cls(info["displayname"], info["id"])

    def __post_init__(self) -> None:
        from isisdl.backend.checksums import CheckSumHandler
        # Avoid problems where Professors decide to put "/" in the name of the course. In unix a "/" not part of the directory-name-language.
        self.name = sanitize_name_for_dir(self.name)

        # Instantiate the CheckSumHandler
        self.checksum_handler = CheckSumHandler(self)

    def prepare_dirs(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(path(download_dir_location, self.name, item), exist_ok=True)

        for item in MediaType.list_excluded_dirs():
            os.makedirs(path(download_dir_location, self.name, item), exist_ok=True)

    def download_videos(self, s: SessionWithKey):
        url = "https://isis.tu-berlin.de/lib/ajax/service.php"
        # Thank you isia_tub for this field <3
        video_data = [{
            "index": 0,
            "methodname": "mod_videoservice_get_videos",
            "args": {"coursemoduleid": 0, "courseid": self.course_id}
        }]

        videos_json = s.s.get(url, params={"sesskey": s.key}, json=video_data).json()[0]

        if videos_json["error"]:
            log_level = logger.error
            if "get_in_or_equal() does not accept empty arrays" in videos_json["exception"]["message"]:
                # This is a ongoing bug in ISIS. If a course does not have any videos an exception is raised.
                # This pushes it to the debug level.
                log_level = logger.debug

            log_level(f"I had a problem getting the videos for the course {self}:\n{videos_json}\nI am not downloading the videos!")
            videos = []

        else:
            videos = [item for item in videos_json["data"]["videos"]]

        return videos

    def download_content(self, helper: RequestHelper):
        content = helper.post_REST('core_course_get_contents', {"courseid": self.course_id})
        for week in content:
            for file in week["modules"]:
                if "url" not in file:
                    return

                url = file["url"]

                if any(item in url for item in {"mod/url", "mod/page", "mod/forum", "mod/assign", "mod/feedback", "mod/quiz", "mod/videoservice", "mod/etherpadlite",
                                                "mod/questionnaire", "availability/condition", "mod/lti", "mod/scorm", "mod/choicegroup", "mod/glossary", "mod/choice",
                                                "mod/choicegroup", "mailto:", "tu-berlin.zoom.us", "@campus.tu-berlin.de", "mod/h5pactivity", "meet.isis.tu-berlin.de",
                                                "course/view.php", "mod/ratingallocate"}):
                    # These links are definite blacklists on stuff we don't want to follow.
                    break


        return []

    @property
    def url(self) -> str:
        return "https://isis.tu-berlin.de/course/view.php?id=" + self.course_id

    def path(self, *args) -> str:
        """
        Custom path function that prepends the args with the `download_dir` and course name.
        """
        return path(download_dir_location, self.name, *args)

    def list_files(self) -> Iterable[Path]:
        for directory in Path(path(download_dir_location, self.name)).glob("*"):
            if not directory.stem.startswith(".") and directory.stem not in MediaType.list_excluded_dirs():
                for file in directory.rglob("*"):
                    if not file.is_dir():
                        yield file

    @property
    def ok(self):
        if args.whitelist != [True] and self in args.whitelist:
            return True

        return self in args.whitelist and self not in args.blacklist

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{self.name} ({self.course_id})"

    def __eq__(self, other):
        if other is True:
            return True

        if other.__class__ == self.__class__:
            return self.course_id == other.course_id

        if isinstance(other, str):
            return self.course_id == other

        return int(self.course_id) == other

    def finish(self):
        self.checksum_handler.dump()


def with_timing(course_downloader_entry: str):
    def decorator(function):
        def _impl(*method_args, **method_kwargs):
            s = time.perf_counter()
            method_output = function(*method_args, **method_kwargs)
            CourseDownloader.timings[course_downloader_entry] += time.perf_counter() - s

            return method_output

        return _impl

    return decorator


@dataclass
class RequestHelper:
    user: User
    sessions: Optional[List[SessionWithKey]] = None
    courses: Optional[List[Course]] = None
    _meta_info: Dict[str, str] = field(default_factory=lambda: {})

    default_headers = {
        "User-Agent": "UwU",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def __post_init__(self):
        self.make_sessions()
        self._get_meta_info()
        self._get_courses()

        assert self.sessions is not None
        assert self.courses is not None

    def _authenticate(self, num: int) -> SessionWithKey:
        s = Session()
        s.headers.update({"User-Agent": "UwU"})

        s.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")

        s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s1",
               data={"shib_idp_ls_exception.shib_idp_session_ss": "", "shib_idp_ls_success.shib_idp_session_ss": "false", "shib_idp_ls_value.shib_idp_session_ss": "",
                     "shib_idp_ls_exception.shib_idp_persistent_ss": "", "shib_idp_ls_success.shib_idp_persistent_ss": "false", "shib_idp_ls_value.shib_idp_persistent_ss": "",
                     "shib_idp_ls_supported": "", "_eventId_proceed": "", })

        response = s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
                          params={"j_username": self.user.username, "j_password": self.user.password, "_eventId_proceed": ""})

        if response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            # The redirection did not work → credentials are wrong
            logger.error(f"I had a problem getting the {self.user = !s}. You have probably entered the wrong credentials.\nBailing out…")
            os._exit(69)

        if num == 0:
            logger.info(f"Credentials for {self.user} accepted!")

        # Extract the session key
        soup = BeautifulSoup(response.text, features="html.parser")
        key = soup.find("input", {"name": "sesskey"})["value"]

        try:
            # This is a somewhat dirty hack.
            # In order to obtain a token one usually calls the `login/token.php` site, however since ISIS handles authentication via SSO, this always results in an invalid password.
            # In https://github.com/C0D3D3V/Moodle-Downloader-2/wiki/Obtain-a-Token#get-a-token-with-sso-login this way of obtaining the token is described.
            # I would love to get a better way working, but unfortunately it seems as if it is not supported.
            s.get("https://isis.tu-berlin.de/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=12345&urlscheme=moodledownloader")
            raise requests.exceptions.InvalidSchema
        except requests.exceptions.InvalidSchema as ex:
            token = base64.standard_b64decode(str(ex).split("token=")[-1]).decode().split(":::")[1]

        return SessionWithKey(s, key, token)

    @debug_time("Creating RequestHelper")
    def make_sessions(self):
        if RequestHelper.sessions is None:
            with ThreadPoolExecutor(num_sessions) as ex:
                self.sessions = list(ex.map(self._authenticate, range(num_sessions)))

    def _get_meta_info(self) -> None:
        self._meta_info = self.post_REST('core_webservice_get_site_info')

    def _get_courses(self):
        self.courses = [Course.from_dict(item) for item in self.post_REST('core_enrol_get_users_courses', {"userid": self.userid})]

    def post_REST(self, function: str, data: {str: str} = None) -> Optional[Dict]:
        data = data or {}
        s: SessionWithKey = random.choice(self.sessions)
        data.update({
            "moodlewssettingfilter": "true",
            "moodlewssettingfileurl": "true",
            "moodlewsrestformat": "json",
            'wsfunction': function,
            'wstoken': s.token
        })

        url = f"https://isis.tu-berlin.de/webservice/rest/server.php"

        response = s.s.post(url, data=data, headers=self.default_headers, timeout=download_timeout)

        if response:
            return response.json()
        return None

    # Maybe?
    #   'mod_scorm_get_scorms_by_courses'

    def download_unlikely(self):
        for func in ['mod_data_get_databases_by_courses', 'mod_book_get_books_by_courses', 'mod_book_get_books_by_courses', 'mod_imscp_get_imscps_by_courses']:
            response = self.post_REST(func)
            if any(item for item in response.values()):
                logger.debug(f"Found something in {func}: {response}")

    def download_assignments(self):
        # TODO: 'mod_assign_get_submissions'
        assignments = [item["assignments"] for item in self.post_REST('mod_assign_get_assignments')["courses"]]
        return [item for row in assignments for item in row]

    def download_folders(self):
        return self.post_REST('mod_folder_get_folders_by_courses')["folders"]

    def download_resources(self):
        return self.post_REST('mod_resource_get_resources_by_courses')["resources"]


    def download_content(self):
        num = len(self.courses)
        sessions = random.choices(self.sessions, k=num)
        with ThreadPoolExecutor(num) as ex:
            video_lists = list(ex.map(lambda course, s, helper: course.download_videos(s) + course.download_content(helper), self.courses, sessions, repeat(self)))

        return [item for row in video_lists for item in row]

        return

    @property
    def userid(self):
        return self._meta_info["userid"]


class CourseDownloader:
    timings: Dict[str, float] = {
        "Creating RequestHelper": 0,
        "Building all files": 0,
        "Instantiating & Calculating file object": 0,
        "Downloading file": 0,
    }
    do_shutdown: bool = False
    helper: Optional[RequestHelper] = None

    def __init__(self, user: User):
        self.user = user

    def start(self):
        def time_func(func: Callable[[], None], entry: str) -> None:
            s = time.perf_counter()
            func()
            CourseDownloader.timings[entry] = time.perf_counter() - s
            maybe_shutdown()

        def maybe_shutdown():
            if CourseDownloader.do_shutdown:
                exit(0)

        self.make_helper()
        files_json = self.build_files()
        self.make_files(files_json)

        # time_func(self.find_courses, "course")
        # time_func(self.build_file_list, "build")
        # time_func(self.build_checksums, "instantiate_and_checksum")
        #
        # time_func(self.check_for_conflicts_in_files, "conflict")
        #
        # status.add_files(CourseDownloader.files)
        #
        # # Make the runner a thread in case of a user needing to exit the program (done by the main-thread)
        # Thread(target=self.download_runner).start()

    @with_timing("Creating RequestHelper")
    def make_helper(self):
        self.helper = RequestHelper(self.user)

    @with_timing("Building all files")
    def build_files(self) -> Dict[str, List[dict]]:
        return self.helper.download_content()

    @with_timing("Instantiating & Calculating file object")
    def make_files(self, files_json: Dict[str, List[dict]]):
        for category, files in files_json.items():
            for item in files:
                MediaContainer.from_dict(self.helper, category, item)
        return

    def finish(self):
        pass
