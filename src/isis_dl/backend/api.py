"""
This file manages all interaction with the Shibboleth service and ISIS in general.
"""
from __future__ import annotations

import logging
import os
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import repeat
from queue import Queue
from threading import Thread
from typing import List

import requests
from bs4 import BeautifulSoup

from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.share.settings import download_dir, enable_multithread
from isis_dl.share.utils import User, args, path, MediaType, debug_time, MediaContainer, sanitize_name_for_dir, Status


@dataclass
class Course:
    s: requests.Session
    name: str
    course_id: str

    def __post_init__(self) -> None:
        # Avoid problems where Professors decide to put "/" in the name of the course. In unix a "/" not part of the directory-name-language.
        self.name = sanitize_name_for_dir(self.name)

        # Instantiate the CheckSumHandler
        self.checksum_handler = CheckSumHandler(self)

    # @classmethod
    # def from_path(cls, s: requests.Session, course_name: str):
    #     """
    #     Creates and returns the Course object from a given path.
    #
    #     Will return None if the metadata file was not found.
    #
    #     :param s: The Session to download with
    #     :param course_name: The name of the directory containing a metadata file. This is prepended with `working_dir` and `download_dir`
    #     :return: The Course object
    #     """
    #     try:
    #         with open(path(download_dir, course_name, metadata_file)) as f:
    #             return cls(s, **json.load(f))
    #
    #     except FileNotFoundError:
    #         logging.error(f"The metadata file of the course {course_name!r} was not found. Aborting!")

    def prepare_dirs(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(path(download_dir, self.name, item), exist_ok=True)

    @property
    def url(self) -> str:
        return "https://isis.tu-berlin.de/course/view.php?id=" + self.course_id

    @debug_time(func_to_call=lambda self: f"Download {self.name!r}", debug_level=logging.info)  # type: ignore
    def download(self, session_key: str) -> List[MediaContainer]:
        """
        Downloads the contents of the Course.
        Will output the timing on the DEBUG log.

        :return: None
        """

        def get_url(queue: Queue[requests.Response], url: str, **kwargs):
            queue.put(self.s.get(url, **kwargs))

        doc_queue: Queue[requests.Response] = Queue()
        vid_queue: Queue[requests.Response] = Queue()

        @debug_time(f"Build file list of course {self.name!r}")
        def build_file_list():
            # First handle documents → This takes the majority of time
            doc_dl = Thread(target=get_url, args=(doc_queue, "https://isis.tu-berlin.de/course/resources.php",), kwargs={"params": {"id": self.course_id}})
            doc_dl.start()

            # Now handle videos
            # Thank you isia_tub for this field <3
            video_data = [{
                "index": 0,
                "methodname": "mod_videoservice_get_videos",
                "args": {"coursemoduleid": 0, "courseid": self.course_id}
            }]

            vid_dl = Thread(target=get_url, args=(vid_queue, "https://isis.tu-berlin.de/lib/ajax/service.php",), kwargs={"params": {"sesskey": session_key}, "json": video_data})
            vid_dl.start()

            vid_dl.join()
            doc_dl.join()

        #
        build_file_list()

        res_soup = BeautifulSoup(doc_queue.get().text)
        resources = [item["href"] for item in res_soup.find("div", {"role": "main"}).find_all("a")]

        videos_json = vid_queue.get().json()[0]

        if videos_json["error"]:
            log_level = logging.error
            if "get_in_or_equal() does not accept empty arrays" in videos_json["exception"]["message"]:
                # This is a ongoing bug in ISIS. If a course does not have any videos an exception is raised.
                # This pushes it to the debug level.
                log_level = logging.debug

            log_level(f"I had a problem getting the videos for the course {self.name!r}:\n{videos_json}\nI am not downloading the videos!")
            videos = []

        else:
            videos = [item for item in videos_json["data"]["videos"]]

        if enable_multithread:
            @debug_time(f"Instantiating objects for course {self.name!r}")
            def instantiate() -> List[MediaContainer]:
                with ThreadPoolExecutor(4) as ex:
                    a = ex.map(MediaContainer.from_url, repeat(self.s), resources, repeat(self), repeat(session_key))
                    b = ex.map(MediaContainer.from_video, repeat(self.s), videos, repeat(self))

                return list(a) + list(b)

            return instantiate()  # type: ignore

        else:
            @debug_time(f"Instantiating objects for course {self.name!r}")
            def instantiate():
                return [MediaContainer.from_url(self.s, url, self, session_key) for url in resources] + [MediaContainer.from_video(self.s, video, self) for video in videos]

            # nums = [item.download() for item in filter(None, to_download)]  # type: ignore

            return instantiate()  # type: ignore

        # logging.info(f"Downloaded {sum(nums)} files from the course {self.name!r}")
        #
        # if args.file_list and sum(nums):
        #     file_list = "\n".join(file.name for file, is_downloaded in zip(filter(None, to_download), nums) if is_downloaded and file is not None)  # type: ignore
        #     logging.info(f"Downloaded files:\n{file_list}")

    def path(self, *args) -> str:
        """
        Custom path function that prepends the args with the `download_dir` and course name.
        """
        return path(download_dir, self.name, *args)

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.__str__()

    def finish(self):
        self.checksum_handler.dump()


@dataclass
class CourseDownloader:
    s: requests.Session
    user: User
    courses: List[Course] = field(default_factory=lambda: list())

    @classmethod
    def from_user(cls, user: User):
        return cls(requests.Session(), user)

    @debug_time("Authentication with Shibboleth")
    def _authenticate(self) -> str:
        self.s.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")

        self.s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s1",
                    data={"shib_idp_ls_exception.shib_idp_session_ss": "", "shib_idp_ls_success.shib_idp_session_ss": "false", "shib_idp_ls_value.shib_idp_session_ss": "",
                          "shib_idp_ls_exception.shib_idp_persistent_ss": "", "shib_idp_ls_success.shib_idp_persistent_ss": "false", "shib_idp_ls_value.shib_idp_persistent_ss": "",
                          "shib_idp_ls_supported": "", "_eventId_proceed": "", })

        response = self.s.post("https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
                               params={"j_username": self.user.username, "j_password": self.user.password, "_eventId_proceed": ""})

        if response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            # The redirection did not work → credentials are wrong
            logging.error(f"I had a problem getting the {self.user = !s}. You have probably entered the wrong credentials.\nBailing out…")
            exit(69)

        logging.info(f"Credentials for {self.user} accepted!")

        # Extract the session key
        soup = BeautifulSoup(response.text)
        session_key: str = soup.find("input", {"name": "sesskey"})["value"]

        return session_key

    @debug_time("Find Courses")
    def _find_courses(self):
        soup = BeautifulSoup(self.s.get("https://isis.tu-berlin.de/user/profile.php?lang=en").text)

        links = []
        titles = []
        for item in soup.find("div", {"role": "main"}).find_all("a"):
            if "course" in item["href"]:
                links.append(item["href"])
                titles.append(item.text)

        def find_course_id(url: str):
            return url.split("/")[-1].split("course=")[-1]

        courses = [Course(self.s, title, find_course_id(link)) for title, link in zip(titles, links)]

        # Debug feature such that I only have to deal with one course at a time
        courses = courses[3:4]

        for course in courses:
            course.prepare_dirs()

        return courses

    def start(self):
        session_key = self._authenticate()
        self.courses = self._find_courses()

        if enable_multithread:
            with ThreadPoolExecutor(len(self.courses)) as ex:
                _to_download = list(ex.map(lambda x, y: x.download(y), self.courses, repeat(session_key)))  # type: ignore

        else:
            _to_download = [item.download(session_key) for item in self.courses]

        # Collapse and filter the list of lists
        to_download = [item for row in _to_download for item in row if item is not None]

        # We shuffle the data to generate a uniform distribution of documents and videos. Documents need more threads and videos bandwidth.
        # If they are downloaded at the "same" time the utilization maximizes.
        random.shuffle(to_download)

        watcher = Status(to_download)
        watcher.start()

        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads) as ex:
                ex.map(lambda x: x.download(), to_download)  # type: ignore
        else:
            for item in to_download:
                item.download()

        watcher.finish()

    def finish(self):
        for item in self.courses:
            item.finish()
