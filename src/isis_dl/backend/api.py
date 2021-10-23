"""
This file manages all interaction with the Shibboleth service and ISIS in general.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import repeat
from json import JSONDecodeError
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import List, Optional, Iterable

import requests
from bs4 import BeautifulSoup

from isis_dl.backend.checksums import CheckSumHandler
from isis_dl.share.settings import download_dir_location, enable_multithread, course_name_to_id_file_location, \
    sleep_time_for_download_interrupt
from isis_dl.share.utils import User, args, path, MediaType, debug_time, MediaContainer, sanitize_name_for_dir, on_kill, status, DownloadStatus, logger


@dataclass
class Course:
    s: requests.Session
    name: str
    course_id: str

    @classmethod
    def from_name(cls, name: str):
        try:
            with open(path(course_name_to_id_file_location)) as f:
                the_id = json.load(f)[name]

        except (FileNotFoundError, KeyError, JSONDecodeError) as ex:
            logger.error(f"Malformed file {path(course_name_to_id_file_location)!r}.")
            raise ex

        return cls(requests.Session(), name, the_id)

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
    #         logger.error(f"The metadata file of the course {course_name!r} was not found. Aborting!")

    def prepare_dirs(self) -> None:
        for item in MediaType.list_dirs():
            os.makedirs(path(download_dir_location, self.name, item), exist_ok=True)

        for item in MediaType.list_excluded_dirs():
            os.makedirs(path(download_dir_location, self.name, item), exist_ok=True)

    @property
    def url(self) -> str:
        return "https://isis.tu-berlin.de/course/view.php?id=" + self.course_id

    @debug_time(func_to_call=lambda self: f"Download {self!r}", debug_level=logging.info)  # type: ignore
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

        @debug_time(f"Build file list of course {self}")
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
            log_level = logger.error
            if "get_in_or_equal() does not accept empty arrays" in videos_json["exception"]["message"]:
                # This is a ongoing bug in ISIS. If a course does not have any videos an exception is raised.
                # This pushes it to the debug level.
                log_level = logger.debug

            log_level(f"I had a problem getting the videos for the course {self}:\n{videos_json}\nI am not downloading the videos!")
            videos = []

        else:
            videos = [item for item in videos_json["data"]["videos"]]

        if enable_multithread:
            @debug_time(f"Instantiating objects for course {self}")
            def instantiate() -> List[MediaContainer]:
                with ThreadPoolExecutor(4) as ex:
                    a = ex.map(MediaContainer.from_url, repeat(self.s), resources, repeat(self), repeat(session_key))
                    b = ex.map(MediaContainer.from_video, repeat(self.s), videos, repeat(self))

                return list(a) + list(b)

            return instantiate()  # type: ignore

        else:
            @debug_time(f"Instantiating objects for course {self}")
            def instantiate():
                return [MediaContainer.from_url(self.s, url, self, session_key) for url in resources] + [MediaContainer.from_video(self.s, video, self) for video in videos]

            # nums = [item.download() for item in filter(None, to_download)]  # type: ignore

            return instantiate()  # type: ignore

        # logger.info(f"Downloaded {sum(nums)} files from the course {self.name!r}")
        #
        # if args.file_list and sum(nums):
        #     file_list = "\n".join(file.name for file, is_downloaded in zip(filter(None, to_download), nums) if is_downloaded and file is not None)  # type: ignore
        #     logger.info(f"Downloaded files:\n{file_list}")

    def path(self, *args) -> str:
        """
        Custom path function that prepends the args with the `download_dir` and course name.
        """
        return path(download_dir_location, self.name, *args)

    def list_files(self) -> Iterable[Path]:
        for directory in Path(path(download_dir_location, self.name)).glob("*"):
            if not directory.stem.startswith(".") and directory.stem not in MediaType.list_excluded_dirs():
                for file in directory.rglob("*"):
                    yield file

    @property
    def ok(self):
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
    downloading: Optional[List[MediaContainer]] = None
    _tried_shutdown: bool = False

    def __init__(self, s: requests.Session, user: User):
        self.s = s
        self.user = user

        self.courses: List[Course] = []

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
            logger.error(f"I had a problem getting the {self.user = !s}. You have probably entered the wrong credentials.\nBailing out…")
            exit(69)

        logger.info(f"Credentials for {self.user} accepted!")

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

        courses = list(filter(lambda x: x.ok, courses))

        if len(courses) == 0:
            logger.warning(f"The {len(courses) = }. I am not downloading anything!")
            exit(0)

        for course in courses:
            course.prepare_dirs()

        return courses

    def start(self):
        session_key = self._authenticate()
        self.courses = self._find_courses()

        # TODO Speed this up and shift away
        if enable_multithread:
            with ThreadPoolExecutor(len(self.courses)) as ex:
                _to_download = list(ex.map(lambda x, y: x.download(y), self.courses, repeat(session_key)))  # type: ignore

        else:
            _to_download = [item.download(session_key) for item in self.courses]

        # Collapse and filter the list of lists. Here we assign it to the Class in order to access it statically later.
        CourseDownloader.downloading = [item for row in _to_download for item in row if item is not None]

        # We shuffle the data to generate a uniform distribution of documents and videos. Documents need more threads and videos bandwidth.
        # If they are downloaded at the "same" time the utilization maximizes.
        random.shuffle(CourseDownloader.downloading)

        self.download_runner(CourseDownloader.downloading)

    def download_runner(self, to_download: List[MediaContainer]):
        status.add_files(to_download)

        if enable_multithread:
            with ThreadPoolExecutor(args.num_threads) as ex:
                ex.map(lambda x: x.download(), to_download)  # type: ignore
        else:
            for item in to_download:
                item.download()

        new_files = [item for item in to_download if item.status == DownloadStatus.succeeded]
        if args.file_list and new_files:
            logger.info("Newly downloaded files:\n" + "\n".join(item.name for item in sorted(new_files)))

    @staticmethod
    @on_kill(-2)
    def shutdown_running_downloads(*_):
        to_download = CourseDownloader.downloading
        if to_download is None:
            return

        for item in to_download:
            item.stop_download(CourseDownloader._tried_shutdown)

        CourseDownloader._tried_shutdown = True

        # Now wait for the downloads to finish
        while not all(item.status.done_or_stopped for item in to_download):
            time.sleep(sleep_time_for_download_interrupt)

    def finish(self):
        # Update the course - id mapping
        previous_mapping = {}
        try:
            with open(path(course_name_to_id_file_location)) as f:
                previous_mapping = json.load(f)
        except (FileNotFoundError, JSONDecodeError):
            pass

        current_mapping = {item.name: item.course_id for item in self.courses}

        # Only write changes if they are necessary
        if current_mapping != previous_mapping:
            previous_mapping.update(current_mapping)

            with open(path(course_name_to_id_file_location), "w") as f:
                json.dump(previous_mapping, f, indent=4, sort_keys=True)

        for item in self.courses:
            item.finish()
