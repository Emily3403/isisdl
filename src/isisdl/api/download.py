from __future__ import annotations

import asyncio
from asyncio import Event
from collections import defaultdict

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.crud import sort_courses, download_media_url, filter_bad_urls, read_downloaded_urls_to_dict, create_downloaded_urls
from isisdl.api.endpoints import DocumentListAPI, VideoListAPI
from isisdl.api.models import DownloadedURL, MediaURL, AuthenticatedSession, Course, TempURL
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


async def download_media_urls(db: DatabaseSession, session: AuthenticatedSession, urls: list[MediaURL], config: Config) -> list[DownloadedURL] | None:
    """
    This is the main function that downloads the files from the web. It does so by following these steps:

    1. Filter out bad urls, already downloaded and duplicate urls.

    2. For each course, download the all files except videos as temporary files and save them.
       - Courses are downloaded first by time of access or modification. These are completed in order, with max parallelism of `TODO`.
       - Paths are derived as a hash based on `url` (not `download_url`).
       - Videos are not downloaded here, because they are already deduplicated on ISIS.
         They have a sha256sum in their url to ensure this.
         Also, with their big file size it takes a *lot* of time for them to get downloaded. Thus, we want another download strategy

    3. Conflict resolution based on file hashes is done.
       - Merge all identical hashes into one file that links to the others.
       - Check all paths to be created for duplicates.
         Doing this deterministically is very important because otherwise files would be overwritten at random.
         So, sort the files by `url` and additional files with `.1.pdf`, `.2.pdf`, etc. get created.
         (Of course, these also have to be checked for conflicts as another file could already be there)

    4. Download videos (TODO)

    - Try to figure out names / attributes from the URL
    """

    # TODO: Filter out already downloaded URLs
    # TODO: Filter out duplicates
    urls_to_download, urls_per_course, courses = filter_bad_urls(db, urls), defaultdict(list), set()

    for url in urls_to_download:
        courses.add(url.course)
        urls_per_course[url.course_id].append(url)

    stop = Event()  # TODO: Migrate this to somewhere where @onkill can use it
    rate_limiter = RateLimiter.from_bandwidth(250)  # TODO: Make this configurable

    downloads: list[DownloadedURL] = []
    existing_media_containers = read_downloaded_urls_to_dict(db)

    # courses_to_download = [it for it in courses if it.id == 36966]
    sorted_courses = sort_courses(courses)

    # Now, filter duplicates and collisions in paths
    # TODO: How big is this async-pool? How many tasks will be launched in parallel?
    for response, course in zip(asyncio.as_completed([
        download_temporary_files(db, session, rate_limiter, urls_per_course[course.id], course, stop, priority=i, config=config) for i, course in enumerate(sorted_courses)
    ]), sorted_courses):
        r = await response
        down = await create_downloaded_urls(db, r, course.id, existing_media_containers, config)
        if down is None:
            continue  # TODO

        downloads.extend(down)

    return downloads


async def download_temporary_files(db: DatabaseSession, session: AuthenticatedSession, rate_limiter: RateLimiter, urls: list[MediaURL], course: Course, stop: Event, priority: int, config: Config) -> list[TempURL]:
    """
    This function downloads the media urls (belonging to a course) as temporary files.
    Assumption is that urls are filtered by course.
    """

    await rate_limiter.register_course(course)
    temp_files = []

    # TODO: How big is this async-pool? How many tasks will be launched in parallel?
    for response in asyncio.as_completed([download_media_url(db, session, rate_limiter, url, course, stop, priority, config) for url in urls]):
        temp_files.append(await response)

    rate_limiter.complete_course(course)
    return [file for file in temp_files if isinstance(file, TempURL)]
