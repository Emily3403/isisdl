from __future__ import annotations

import asyncio
from asyncio import Event
from collections import defaultdict

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.crud import sort_courses, download_media_url_to_temp_file, filter_bad_urls, create_media_containers_from_temp_files
from isisdl.api.endpoints import DocumentListAPI, VideoListAPI
from isisdl.api.models import MediaContainer, MediaURL, AuthenticatedSession, Course, TempFile
from isisdl.api.rate_limiter import RateLimiter
from isisdl.backend.models import Config


async def gather_media_urls(db: DatabaseSession, session: AuthenticatedSession, courses: list[Course], config: Config) -> list[MediaURL]:
    urls = []
    for response in asyncio.as_completed([
        VideoListAPI.get(db, session, courses, config),
        DocumentListAPI.get(db, session, courses),
    ]):
        urls.extend(await response)

    return urls


async def download_media_urls(db: DatabaseSession, session: AuthenticatedSession, urls: list[MediaURL], config: Config) -> list[MediaContainer] | None:
    """
    This is the main function that downloads the files from the web. It does so by following these steps:

    1. Filter out bad urls and already downloaded urls.
    2. For each course, download the documents as temporary files and save them.
       - Paths are derived as a hash from the URL
       - Courses are sorted based on time of access or modification
       - Videos are not downloaded as there is no possibility of collision due to the sha256 hash in the url
    3. Conflict resolution, based on file hashes, is done.


    - Resolve all conflicts in file paths
      - Develop an algorithm to deterministically sort files based on the optional attributes they have
      - Filter same download url
    - Try to figure out names / attributes from the URL
    - Figure out the order of downloading for the containers

    # To Integrate somewhere
    - Modify download_url based on urls, following Google Drive etc.
        - From ISIS: mod/resource and mod/url need following
    - How to handle bad links?

    """

    # TODO: Filter out already downloaded URLs
    urls_to_download = filter_bad_urls(db, urls)

    urls_per_course = defaultdict(list)
    courses = set()
    for url in urls_to_download:
        courses.add(url.course)
        urls_per_course[url.course_id].append(url)

    stop = Event()  # TODO: Migrate this to somewhere where @onkill can use it
    rate_limiter = RateLimiter.from_bandwidth(250)  # TODO: Make this configurable

    temp_files = []
    download = [download_temporary_files(db, session, rate_limiter, urls_per_course[course.id], course, stop, priority=i, config=config) for i, course in enumerate(sort_courses(courses))]
    for response in asyncio.as_completed(download):
        temp_files.extend(await response)

    # TODO: Measure if it would be worth moving this into the previous loop. A lot of CPU time is free before and now being used.
    return create_media_containers_from_temp_files(db, temp_files)


async def download_temporary_files(db: DatabaseSession, session: AuthenticatedSession, rate_limiter: RateLimiter, urls: list[MediaURL], course: Course, stop: Event, priority: int, config: Config) -> list[TempFile]:
    """
    This function downloads the media urls (belonging to a course) as temporary files.
    Assumption is that urls are filtered by course.
    """

    await rate_limiter.register_course(course)
    temp_files = []

    for response in asyncio.as_completed([download_media_url_to_temp_file(db, session, rate_limiter, url, course, stop, priority, config) for url in urls]):
        temp_files.append(await response)

    rate_limiter.complete_course(course)
    return [file for file in temp_files if isinstance(file, TempFile)]
