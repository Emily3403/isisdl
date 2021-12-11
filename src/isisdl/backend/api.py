"""
This file manages all interaction with the Shibboleth service and ISIS in general.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import List, Optional, Iterable, Callable, Dict, Union

import requests
from bs4 import BeautifulSoup
from requests import Session

from isisdl.backend.checksums import CheckSumHandler
from isisdl.backend.downloads import MediaType, SessionWithKey, MediaContainer, DownloadStatus, status, FailedDownload
from isisdl.share.settings import download_dir_location, enable_multithread, course_name_to_id_file_location, \
    sleep_time_for_download_interrupt, num_sessions
from isisdl.share.utils import User, args, path, debug_time, sanitize_name_for_dir, on_kill, logger, get_text_from_session, get_url_from_session, CriticalError, classproperty


@dataclass
class AlmostMediaContainer:
    func: Callable[[SessionWithKey, Course, Union[str, Dict[str, str]]], MediaContainer]
    s: SessionWithKey
    parent_course: Course
    arg: Union[str, Dict[str, str]]
    is_video: bool
    size: int = 0

    def instantiate(self):
        if CourseDownloader.do_shutdown:
            return

        return self.func(self.s, self.parent_course, self.arg)

    def __str__(self):
        return self.arg


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
            logger.error(f"Malformed file {path(course_name_to_id_file_location)!r}.")
            raise ex

        return cls(name, the_id)

    def __post_init__(self) -> None:
        # Avoid problems where Professors decide to put "/" in the name of the course. In unix a "/" not part of the directory-name-language.
        self.name = sanitize_name_for_dir(self.name)

        # Instantiate the CheckSumHandler
        self.checksum_handler = CheckSumHandler(self)

    def prepare_dirs(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(path(download_dir_location, self.name, item), exist_ok=True)

        for item in MediaType.list_excluded_dirs():
            os.makedirs(path(download_dir_location, self.name, item), exist_ok=True)

    @property
    def url(self) -> str:
        return "https://isis.tu-berlin.de/course/view.php?id=" + self.course_id

    def download(self, parent: CourseDownloader) -> List[AlmostMediaContainer]:
        if CourseDownloader.do_shutdown:
            return []

        def get_url(s: SessionWithKey, queue: Queue[Optional[requests.Response]], url: str, **kwargs):
            queue.put(get_url_from_session(s.s, url, **kwargs))

        doc_queue: Queue[Optional[requests.Response]] = Queue()
        other_queue: Queue[Optional[requests.Response]] = Queue()
        vid_queue: Queue[Optional[requests.Response]] = Queue()

        def build_file_list():
            # First handle documents → This takes the majority of time
            doc_dl = Thread(target=get_url, args=(parent.s, doc_queue, "https://isis.tu-berlin.de/course/resources.php",), kwargs={"params": {"id": self.course_id}})
            doc_dl.start()

            other_dl = Thread(target=get_url, args=(parent.s, other_queue, "https://isis.tu-berlin.de/course/view.php",), kwargs={"params": {"id": self.course_id}})
            other_dl.start()

            # Now handle videos
            # Thank you isia_tub for this field <3
            video_data = [{
                "index": 0,
                "methodname": "mod_videoservice_get_videos",
                "args": {"coursemoduleid": 0, "courseid": self.course_id}
            }]

            s = parent.s
            vid_dl = Thread(target=get_url, args=(s, vid_queue, "https://isis.tu-berlin.de/lib/ajax/service.php",), kwargs={"params": {"sesskey": s.key}, "json": video_data})
            vid_dl.start()

            vid_dl.join()
            other_dl.join()
            doc_dl.join()

        #
        build_file_list()

        resource_req = doc_queue.get()
        other_req = other_queue.get()
        video_req = vid_queue.get()

        if resource_req is None:
            raise CriticalError("I could not get the url for the resources! Please restart me and hope it will work this time.")

        if other_req is None:
            raise CriticalError("I could not get the url for other downloads! Please restart me and hope it will work this time.")

        if video_req is None:
            raise CriticalError("I could not get the url for the videos! Please restart me and hope it will work this time.")

        res_soup = BeautifulSoup(resource_req.text, features="html.parser")
        resources = {item["href"] for item in res_soup.find("div", {"role": "main"}).find_all("a")}

        other_soup = BeautifulSoup(other_req.text, features="html.parser")
        resources.update([item.attrs["href"] for item in other_soup.find("div", {"role": "main"}).find_all("a") if "href" in item.attrs])
        videos_json = video_req.json()[0]

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

        # Do some additional parsing for exercises as they contain more resources
        assignments = [item for item in resources if "mod/assign" in item]

        def get_assignment(assignment: str):
            req = get_url_from_session(parent.s.s, assignment)
            if req is None or not req.ok:
                raise CriticalError("I could not get the resources from the exercises! Please restart me and hope it will work this time.")

            req_soup = BeautifulSoup(req.text, features="html.parser")
            links = req_soup.find_all("div", {"class": "fileuploadsubmission"})
            for item in links:
                for new_url in item.find_all("a"):
                    if "href" in new_url.attrs:
                        resources.update({new_url.attrs["href"]})

        if assignments:
            with ThreadPoolExecutor(len(assignments)) as ex:
                ex.map(get_assignment, assignments)

        x = [AlmostMediaContainer(MediaContainer.from_url, parent.s, self, resource, False) for resource in resources]  # type: ignore
        y = [AlmostMediaContainer(MediaContainer.from_video, parent.s, self, video, True) for video in videos]  # type: ignore

        return x + y

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


class CourseDownloader:
    sessions: List[SessionWithKey] = []
    courses: List[Course] = []
    not_inst_files: List[AlmostMediaContainer] = []
    files: List[MediaContainer] = []

    timings: Dict[str, Optional[float]] = {
        "auth": None,
        "course": None,
        "build": None,
        "checksum": None,
        "conflict": None,
        "download": None,
        "checksum_mod/folder": 0,
        "checksum_mod/resource": 0,
        "checksum_rest": 0,
    }
    do_shutdown: bool = False
    downloading_files: bool = False

    def __init__(self, user: User):
        self.user = user

    def start(self):
        def time_func(func: Callable[[], None], entry: str) -> None:
            s = time.time()
            func()
            CourseDownloader.timings[entry] = time.time() - s
            maybe_shutdown()

        def maybe_shutdown():
            if CourseDownloader.do_shutdown:
                exit(0)

        time_func(self.authenticate_all, "auth")
        time_func(self.find_courses, "course")
        time_func(self.build_file_list, "build")
        time_func(self.build_checksums, "checksum")
        time_func(self.check_for_conflicts_in_files, "conflict")

        status.add_files(CourseDownloader.files)

        # Make the runner a thread in case of a user needing to exit the program (done by the main-thread)
        Thread(target=self.download_runner).start()

    @debug_time("Authentication with Shibboleth")
    def _authenticate(self, num: int) -> SessionWithKey:
        if CourseDownloader.do_shutdown:
            return SessionWithKey(Session(), "")

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

        return SessionWithKey(s, key)

    def authenticate_all(self) -> None:
        with ThreadPoolExecutor(num_sessions) as ex:
            CourseDownloader.sessions = list(ex.map(self._authenticate, range(num_sessions)))

    def find_courses(self):
        soup = BeautifulSoup(get_text_from_session(CourseDownloader.s.s, "https://isis.tu-berlin.de/user/profile.php?lang=en"), features="html.parser")

        links = []
        titles = []
        for item in soup.find("div", {"role": "main"}).find_all("a"):
            if item.get("href") and "course" in item["href"]:
                links.append(item["href"])
                titles.append(item.text)

        def find_course_id(url: str):
            return url.split("/")[-1].split("course=")[-1]

        courses = [Course(title, find_course_id(link)) for title, link in zip(titles, links)]

        logger.debug("Found the following courses:\n" + "\n".join(repr(item) for item in courses))

        courses = list(filter(lambda x: x.ok, courses))

        if len(courses) == 0:
            logger.warning(f"The {len(courses) = }. I am not downloading anything!")
            os._exit(1)
        else:
            logger.info("I am downloading the following courses:\n" + "\n".join(repr(item) for item in courses))

        for course in courses:
            course.prepare_dirs()

        CourseDownloader.courses = courses

    @debug_time("Building file list", debug_level=logging.INFO)
    def build_file_list(self) -> None:
        # TODO: Get file url redirect and filter unnecessary out

        # First we get all the possible files
        if enable_multithread:
            with ThreadPoolExecutor(len(CourseDownloader.courses)) as ex:
                _files = list(ex.map(lambda x: x.download(self), CourseDownloader.courses))  # type: ignore
        else:
            _files = [item.download(self) for item in CourseDownloader.courses]

        files = [item for row in _files for item in row if item is not None]

        # We shuffle the data to generate a uniform distribution of documents and videos. Documents need more threads and videos bandwidth.
        # If they are downloaded at the "same" time the utilization maximizes.
        random.shuffle(files)

        CourseDownloader.not_inst_files = files

    @debug_time("Building checksums", debug_level=logging.INFO)
    def build_checksums(self):
        files = CourseDownloader.not_inst_files

        # Now instantiate the objects. This can be more efficient with ThreadPoolExecutor(requests) + multiprocessing
        to_download: List[MediaContainer]
        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads_instantiate) as ex:
                to_download = list(filter(None, ex.map(lambda x: x.instantiate(), files)))  # type: ignore

        else:
            to_download = [item for file in files if (item := file.instantiate()) is not None]

        to_download = list(set(to_download))
        random.shuffle(to_download)
        CourseDownloader.files = to_download

    @staticmethod
    def check_for_conflicts_in_files():
        conflicts = defaultdict(list)
        for item in CourseDownloader.files:
            conflicts[item.name].append(item)

        items = [sorted(item, key=lambda x: x.date if x.date is not None else -1) for item in conflicts.values() if len(item) != 1]  # type: ignore
        for row in items:
            for i, item in enumerate(row):
                basename, ext = os.path.splitext(item.name)
                item.name = basename + f"({i}-{len(row) - 1})" + ext

    def download_runner(self):
        if not self.files:
            logger.error("No files to download! Exiting!")
            return

        s = time.time()
        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads) as ex:
                ex.map(lambda x: x.download(), self.files)  # type: ignore
        else:
            for item in self.files:
                item.download()

        CourseDownloader.timings["download"] = time.time() - s

        new_files, fixable_failed_files, unfixable_failed_files = defaultdict(list), defaultdict(list), defaultdict(list)
        for item in self.files:
            if item.status == DownloadStatus.succeeded:
                new_files[item.parent_course.name].append(item)

            if isinstance(item.status, FailedDownload):
                if item.status.fixable:
                    fixable_failed_files[item.parent_course.name].append(item)
                else:
                    unfixable_failed_files[item.parent_course.name].append(item)

        def format_files(files: Dict[str, List[MediaContainer]]):
            format_list = []
            for course, items in files.items():
                items.sort()
                format_list.append(course + ":\n    " + "\n    ".join(item.error_format() for item in items))

            return "\n\n".join(format_list)

        if unfixable_failed_files:
            logger.debug("Unfixable failed files:\n" + format_files(unfixable_failed_files))
        else:
            logger.debug("No unfixable failed files.")

        if fixable_failed_files:
            logger.info("Failed files:\n" + format_files(fixable_failed_files))
        else:
            logger.info("No failed files.")

        if new_files:
            logger.info("Newly downloaded files:\n" + format_files(new_files))
        else:
            logger.info("No newly downloaded files.")

    @staticmethod
    @on_kill(-2)
    def shutdown_running_downloads(*_):
        CourseDownloader.do_shutdown = True
        to_download = CourseDownloader.files

        for item in to_download:
            item.stop_download()

        # Now wait for the downloads to finish
        while not all(item.status.done for item in to_download):
            time.sleep(sleep_time_for_download_interrupt)

    def finish(self):
        # Update the course - id mapping
        previous_mapping = {}
        try:
            with open(path(course_name_to_id_file_location)) as f:
                previous_mapping = json.load(f)
        except (FileNotFoundError, JSONDecodeError):
            pass

        current_mapping = {item.name: item.course_id for item in CourseDownloader.courses}

        # Only write changes if they are necessary
        if current_mapping != previous_mapping:
            previous_mapping.update(current_mapping)

            with open(path(course_name_to_id_file_location), "w") as f:
                json.dump(previous_mapping, f, indent=4, sort_keys=True)

        for item in CourseDownloader.courses:
            item.finish()

    @classproperty
    def s(cls) -> SessionWithKey:
        return random.choice(cls.sessions)
