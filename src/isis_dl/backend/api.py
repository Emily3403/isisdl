"""
This file manages all interaction with the Shibboleth service and ISIS in general.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List

import requests
from bs4 import BeautifulSoup

from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.share.settings import download_dir, enable_multithread, metadata_file
from isis_dl.share.utils import User, args, path, MediaType, debug_time, MediaContainer, sanitize_name_for_dir


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

    @classmethod
    def from_path(cls, s: requests.Session, course_name: str):
        """
        Creates and returns the Course object from a given path.

        Will return None if the metadata file was not found.

        :param s: The Session to download with
        :param course_name: The name of the directory containing a metadata file. This is prepended with `working_dir` and `download_dir`
        :return: The Course object
        """
        try:
            with open(path(download_dir, course_name, metadata_file)) as f:
                return cls(s, **json.load(f))

        except FileNotFoundError:
            logging.error(f"The metadata file of the course {course_name!r} was not found. Aborting!")

    def prepare_dirs(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(path(download_dir, self.name, item), exist_ok=True)

    @property
    def url(self) -> str:
        return "https://isis.tu-berlin.de/course/view.php?id=" + self.course_id

    @debug_time(func_to_call=lambda self: f"Download {self.name}")  # type: ignore
    def download(self) -> None:
        """
        Downloads the contents of the Course.
        Will output the timing on the DEBUG log.

        :return: None
        """
        soup = BeautifulSoup(self.s.get(self.url).text, "lxml")

        # First we find all resources such as .pdfs etc…
        resources = BeautifulSoup(self.s.get("https://isis.tu-berlin.de/course/resources.php", params={"id": self.course_id}).text, features="lxml")
        resources = [item["href"] for item in resources.find("div", {"role": "main"}).find_all("a")]

        def _find_session_id():
            # Get s ID
            for item in soup.find_all("a"):
                try:
                    if "https://isis.tu-berlin.de/login/logout.php?" in (url := item["href"]):
                        return url.split("sesskey=")[-1]
                except KeyError:
                    # Some links don't lead to anything. Oh well…
                    pass

            logging.error(f"The ID of the Course {self!r} was not found! Please investigate!")

        session_key = _find_session_id()

        # Thank you isia_tub for this field <3
        video_data = [{
            "index": 0,
            "methodname": "mod_videoservice_get_videos",
            "args": {"coursemoduleid": 0, "courseid": self.course_id}
        }]
        videos = self.s.get("https://isis.tu-berlin.de/lib/ajax/service.php", params={"sesskey": session_key}, json=video_data).json()[0]

        if videos["error"]:
            log_level = logging.error
            if "get_in_or_equal() does not accept empty arrays" in videos["exception"]["message"]:
                # This is a ongoing bug in ISIS. If a course does not have any videos an exception is raised.
                # This pushes it to the debug level.
                log_level = logging.debug

            log_level(f"I had a problem getting the videos for the course {self.name}:\n{videos}\nI am not downloading anything!")

            return

        videos = [item for item in videos["data"]["videos"]]

        # Instantiate all MediaContainer objects from resources and videos.
        to_download = [MediaContainer.from_url(self.s, url, self, session_key) for url in resources] + [MediaContainer.from_video(self.s, video, self) for video in videos]

        # Filter entries that are already found via checksum.
        to_download = list(filter(None, to_download))

        if enable_multithread:
            with ThreadPoolExecutor(args.thread_inner_num) as ex:
                nums = list(ex.map(lambda x: x.download(), to_download))  # type: ignore
        else:
            nums = [item.download() for item in to_download]

        logging.info(f"Downloaded {sum(nums)} files from the course {self.name}")

        if args.file_list and sum(nums):
            file_list = "\n".join(file.name for file, is_downloaded in zip(to_download, nums) if is_downloaded)
            logging.info(f"Downloaded files:\n{file_list}")

    def path(self, *args) -> str:
        """
        Custom path function that prepends the args with the `download_dir` and course name.
        """
        return path(download_dir, self.name, *args)

    def dump(self) -> None:
        """
        Dump metadata info into the directory.
        """
        to_dump = self.__dict__.copy()
        del to_dump["s"]
        del to_dump["checksum_handler"]

        with open(self.path(metadata_file), "w") as f:
            json.dump(to_dump, f, indent=4)

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.__str__()

    def finish(self):
        self.dump()
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
    def _authenticate(self):
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

    @debug_time("Find Courses")
    def _find_courses(self):
        soup = BeautifulSoup(self.s.get("https://isis.tu-berlin.de/user/profile.php?lang=en").text, features="lxml")

        links = []
        titles = []
        for item in soup.find("div", {"role": "main"}).find_all("a"):
            if "course" in item["href"]:
                links.append(item["href"])
                titles.append(item.text)

        def find_course_id(url: str):
            return url.split("/")[-1].split("course=")[-1]

        courses = [Course(self.s, title, find_course_id(link)) for title, link in zip(titles, links)]

        courses = courses[3:4]

        for course in courses:
            course.prepare_dirs()

        return courses

    def start(self):
        self._authenticate()
        self.courses = self._find_courses()

        if enable_multithread:
            with ThreadPoolExecutor(len(self.courses)) as ex:
                ex.map(lambda x: x.download(), self.courses)  # type: ignore

        else:
            for item in self.courses:
                item.download()

    def finish(self):
        for item in self.courses:
            item.finish()
