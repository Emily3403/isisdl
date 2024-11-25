from __future__ import annotations

import asyncio
import os.path
import re
import traceback
from asyncio import Event
from base64 import standard_b64decode
from collections import defaultdict
from datetime import datetime
from email.message import Message
from html import unescape
from itertools import chain
from typing import Any, Literal, cast, DefaultDict, Iterable

import aiofiles
import aiofiles.os
from aiohttp import ClientSession as InternetSession, TCPConnector, ClientConnectorSSLError, ClientConnectorCertificateError, ClientSSLError, ClientConnectorError, ServerDisconnectedError
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.models import AuthenticatedSession, Course, MediaURL, MediaType, NormalizedDocument, BadURL, DownloadedURL, Error, TempURL
from isisdl.api.rate_limiter import RateLimiter
from isisdl.backend.models import User, Config
from isisdl.db_conf import add_or_update_objects_to_database, add_object_to_database
from isisdl.settings import url_finder, isis_ignore, extern_ignore, regex_is_isis_document, regex_is_isis_video, connection_pool_limit, download_chunk_size, DEBUG_ASSERTS, logger
from isisdl.utils import datetime_fromtimestamp_with_None, flat_map, get_download_url_from_url, calculate_local_checksum, get_name_from_headers, reject_wrong_mimetype
from isisdl.version import __version__


async def authenticate_new_session(user: User, config: Config) -> AuthenticatedSession | None:
    session = InternetSession(headers={"User-Agent": f"isisdl (Python aiohttp) version {__version__}"}, connector=TCPConnector(limit=connection_pool_limit))

    # First step of authenticating
    await session.get("https://isis.tu-berlin.de/auth/shibboleth/index.php")
    await session.post(
        "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s1",
        data={
            "shib_idp_ls_exception.shib_idp_session_ss": "",
            "shib_idp_ls_success.shib_idp_session_ss": "false",
            "shib_idp_ls_value.shib_idp_session_ss": "",
            "shib_idp_ls_exception.shib_idp_persistent_ss": "",
            "shib_idp_ls_success.shib_idp_persistent_ss": "false",
            "shib_idp_ls_value.shib_idp_persistent_ss": "",
            "shib_idp_ls_supported": "", "_eventId_proceed": "",
        }
    )

    # Second step: submit the password
    async with session.post(
        "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
        params={"j_username": user.username, "j_password": user.decrypt_password(config), "_eventId_proceed": ""}
    ) as response:

        # Check if authentication succeeded
        if response is None or "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3" in str(response.url):
            return None

        data = {k: unescape(v) for k, v in re.findall('<input type="hidden" name="(.*)" value="(.*)"/>', await response.text())}

    async with session.post(
        "https://isis.tu-berlin.de/Shibboleth.sso/SAML2/POST-SimpleSign",
        data=data
    ) as response:

        # Extract the session key
        _session_key = re.search(r"\"sesskey\":\"(.*?)\"", await response.text())
        if _session_key is None:
            return None

        session_key = _session_key.group(1)

    # Third step: obtain the API-token
    async with session.get(
        "https://isis.tu-berlin.de/admin/tool/mobile/launch.php", allow_redirects=False,
        params={"service": "moodle_mobile_app", "passport": "12345", "urlscheme": "moodledownloader"}
    ) as response:

        encoded_token = re.search("token=(.*)", response.headers["Location"])
        if encoded_token is None:
            return None

        api_token = standard_b64decode(encoded_token.group(1)).decode().split(":::")[1]

    return AuthenticatedSession(session, session_key=session_key, api_token=api_token)


# --- Courses ---

def read_courses(db: DatabaseSession) -> list[Course]:
    return list(db.execute(select(Course)).scalars().all())


def sort_courses(courses: Iterable[Course]) -> list[Course]:
    """
    Sort courses based on time_of_last_access if it is not None,
    otherwise, sort based on time_of_last_modification if it is not None,
    otherwise, sort based on time_of_start if it is not None,
    otherwise, sort based on time_of_end if it is not None,
    """
    earliest = datetime.fromtimestamp(0)

    return sorted(courses, key=lambda course: (
        course.time_of_last_access or earliest,
        course.time_of_last_modification or earliest,
        course.time_of_start or earliest,
        course.time_of_end or earliest
    ), reverse=True)


def parse_courses_from_API(db: DatabaseSession, courses: list[dict[str, Any]], config: Config) -> list[Course] | None:
    existing_courses = {it.id: it for it in read_courses(db)}

    return add_or_update_objects_to_database(
        db, existing_courses, courses, Course, lambda course: course["id"],
        {"id": "id", "preferred_name": "shortname" if config.fs_course_default_shortname else "fullname", "short_name": "shortname", "full_name": "fullname",
         "number_users": "enrolledusercount", "is_favorite": "isfavourite", "time_of_last_access": "lastaccess", "time_of_last_modification": "timemodified", "time_of_start": "startdate", "time_of_end": "enddate"},
        {"time_of_last_access": datetime_fromtimestamp_with_None, "time_of_last_modification": datetime_fromtimestamp_with_None, "time_of_start": datetime_fromtimestamp_with_None, "time_of_end": datetime_fromtimestamp_with_None},
        {"preferred_name"}
    )


# --- Documents ---

def read_media_urls(db: DatabaseSession) -> dict[int, dict[str, MediaURL]]:
    final: DefaultDict[int, dict[str, MediaURL]] = defaultdict(dict)
    for it in db.execute(select(MediaURL)).scalars().all():
        final[it.course_id][it.url] = it

    return dict(final)


def create_documents_from_API(db: DatabaseSession, data: list[NormalizedDocument], existing_documents: dict[str, MediaURL]) -> list[MediaURL] | None:
    _data = cast(list[dict[str, Any]], data)  # Erase the `NormalizedDocument` signature to make mypy happy

    return add_or_update_objects_to_database(
        db, existing_documents, _data, MediaURL, lambda doc: doc["url"],
        {"url": "url", "course_id": "course_id", "media_type": "media_type", "relative_path": "relative_path", "discovered_name": "name", "discovered_size": "size", "discovered_ctime": "isis_ctime", "discovered_mtime": "isis_mtime"},
        {"discovered_ctime": datetime_fromtimestamp_with_None, "discovered_mtime": datetime_fromtimestamp_with_None},
    )


def parse_documents_from_API(db: DatabaseSession, course_id: int, documents: list[dict[str, Any]], existing_documents: dict[str, MediaURL]) -> list[MediaURL]:
    """
    TODO: Revise this docstring as it is not accurate anymore. Maybe a way for a transaction is possible, but I don't see it.

    Note that this function should be called using a `db.begin()` (transaction) for the db parameter as this function will create #Courses commits to the database.
    To save trips to the database, one has to pass existing_documents parameter to this function.
    """

    api_data = list(
        filter(
            lambda it: it != {},

            flat_map(
                lambda it: it.get("contents", [{}]),
                flat_map(
                    lambda it: it.get("modules", [{}]),
                    documents
                )
            )
        )
    )

    regex_data = parse_course_page_with_regex(documents, course_id)
    data = filter_duplicates_and_normalize_documents(api_data, regex_data, course_id)

    return create_documents_from_API(db, data, existing_documents) or []


def parse_course_page_with_regex(documents: list[dict[str, Any]], course_id: int) -> list[dict[str, Any]]:
    files = []

    for url in url_finder.findall(str(documents)):
        if isis_ignore.match(url) is not None or extern_ignore.match(url) is not None:
            continue

        files.append({"fileurl": url, "course_id": course_id, "relative_path": "", "filename": None, "filesize": None, "timecreated": None, "timemodified": None, "type": "url"})

    return files


def filter_duplicates_and_normalize_documents(documents_data: list[dict[str, Any]], regex_data: list[dict[str, Any]], course_id: int) -> list[NormalizedDocument]:
    duplicates = defaultdict(list)

    for it in chain(documents_data, regex_data):
        file = normalize_file(it, course_id)
        if file is None:
            continue

        duplicates[it["fileurl"]].append(file)

    return [resolve_duplicates(files) for files in duplicates.values()]


def normalize_file(file: dict[str, Any], course_id: int) -> NormalizedDocument | None:
    url = file.get("fileurl")
    if url is None:
        return None

    if url.endswith("?forcedownload=1"):
        url = url[:-len("?forcedownload=1")]

    if isis_ignore.match(url) is not None or extern_ignore.match(url) is not None:
        return None

    if regex_is_isis_video.match(url) is not None:
        media_type = MediaType.video
    elif regex_is_isis_document.match(url) is not None or file.get("type") != "url":
        media_type = MediaType.document
    else:
        media_type = MediaType.extern

    return {
        "url": url,
        "course_id": course_id,
        "media_type": media_type,
        "relative_path": (file.get("filepath") or "").lstrip("/"),
        "name": file.get("filename"),
        "size": file.get("filesize"),
        "isis_ctime": file.get("timecreated") or file.get("timemodified"),
        "isis_mtime": file.get("timemodified") or file.get("timecreated"),
    }


def resolve_duplicates(files: list[NormalizedDocument]) -> NormalizedDocument:
    """
    Determinism:
      Files are sorted deterministicly by partitioning each attribute into the "Some" and "None" category.
      Then, each attribute is sorted based on the "Some" category.
      If there are multiple files with different attribute, the first one according to the sort order is chosen.
    """
    if len(files) == 1:
        return files[0]

    def resolve_conflict(attr: Literal["url", "course_id", "media_type", "relative_path", "name", "size", "isis_ctime", "isis_mtime"]) -> Any:
        conflicting_attrs = sorted({it for file in files if (it := file[attr]) is not None})
        if len(conflicting_attrs) == 0:
            return None

        return conflicting_attrs[0]

    return {
        "url": resolve_conflict("url"),
        "course_id": resolve_conflict("course_id"),
        "media_type": resolve_conflict("media_type"),
        "relative_path": resolve_conflict("relative_path"),
        "name": resolve_conflict("name"),
        "size": resolve_conflict("size"),
        "isis_ctime": resolve_conflict("isis_ctime"),
        "isis_mtime": resolve_conflict("isis_mtime"),
    }


# --- Videos ---


def create_videos_from_API(db: DatabaseSession, videos: list[dict[str, Any]], course_id: int, existing_videos: dict[str, MediaURL]) -> list[MediaURL] | None:
    # Filter out duplicate videos
    videos = list({video["url"]: video for video in videos}.values())

    videos = list(map(lambda it: it | {"course_id": course_id, "media_type": MediaType.video, "relative_path": os.path.join("Videos", it["collectionname"]), "size": None, "time_modified": None}, videos))

    return add_or_update_objects_to_database(
        db, existing_videos, videos, MediaURL, lambda video: video["url"],
        {"url": "url", "course_id": "course_id", "media_type": "media_type", "relative_path": "relative_path", "discovered_name": "title", "discovered_size": "size", "discovered_ctime": "timecreated", "discovered_mtime": "time_modified"},
        {"discovered_ctime": datetime_fromtimestamp_with_None, "discovered_mtime": datetime_fromtimestamp_with_None},
    )


def parse_videos_from_API(db: DatabaseSession, videos: list[dict[str, Any]], config: Config) -> list[MediaURL]:
    if config.dl_download_videos is False:
        return []

    existing_videos = read_media_urls(db)

    # TODO: Make this a single transaction instead of one for each course
    return list(
        filter(
            lambda it: it is not None,
            flat_map(
                lambda data: create_videos_from_API(db, data.get("videos"), data.get("courseid"), existing_videos[data["courseid"]]) or [],
                map(lambda it: it.get("data", {}), videos)
            )
        )
    )


# --- Bad URLs ---

def read_bad_urls(db: DatabaseSession) -> dict[tuple[str, int], BadURL]:
    return {(it.url, it.course_id): it for it in db.execute(select(BadURL)).scalars().all()}


def filter_bad_urls(db: DatabaseSession, urls: list[MediaURL]) -> list[MediaURL]:
    bad_urls = read_bad_urls(db)

    good_urls = []
    for url in urls:
        bad_url = bad_urls.get((url.url, url.course_id))
        if bad_url is None or bad_url.should_retry():
            good_urls.append(url)

    return good_urls


def create_bad_url(db: DatabaseSession, url: MediaURL) -> BadURL | None:
    # TODO
    pass


# --- Temp URLs ---

def create_temp_url(db: DatabaseSession, config: Config, url: MediaURL, download_url: str, name: str) -> TempURL | None:
    try:
        path = url.temp_path(config)
        size = path.stat().st_size
        checksum = calculate_local_checksum(path)
        return add_object_to_database(db, TempURL(url=url.url, course_id=url.course_id, version=url.version, name=name, download_url=download_url, checksum=checksum, size=size))

    except FileNotFoundError as ex:
        logger.error(f"Could not open {url.temp_path(config)}: {str(ex)}")
        return None


def get_temp_file(db: DatabaseSession, url: str, course_id: int, version: int) -> TempURL | None:
    return db.get(TempURL, (url, course_id, version))


async def download_media_url(db: DatabaseSession, session: AuthenticatedSession, rate_limiter: RateLimiter, url: MediaURL, course: Course, stop: Event, priority: int, config: Config, extra_args: dict[str, Any] | None = None) -> TempURL | BadURL | None:
    if stop.is_set():
        return None

    try:
        path = url.temp_path(config)

        await aiofiles.os.makedirs(path.parent, exist_ok=True)
        await rate_limiter.register_url(course, url.media_type)

        # Note we do not check if a downloaded_url exists, as there might be multiple and the file could have changed.
        maybe_temp_file = get_temp_file(db, url.url, url.course_id, url.version)
        if maybe_temp_file is not None:
            # Temp file was already downloaded
            try:

                if calculate_local_checksum(path) == maybe_temp_file.checksum:
                    return maybe_temp_file

                logger.error(f"Discovered wrong checksum for file {path}! Re-downloading it!")

            except FileNotFoundError:
                logger.error(f"Got Temp file for {path} but no local file was found! Re-downloading it!")

        download_url = await get_download_url_from_url(db, session, url.url, url.course_id)
        if download_url is None:
            return None  # TODO

        params = {"params": {"token": session.api_token}}
        name = url.discovered_name

        async with aiofiles.open(path, "wb") as f, session.get(download_url, **((extra_args or {}) | params)) as response:
            if reject_wrong_mimetype(response.headers.get("Content-Type")):
                return create_bad_url(db, url)

            if name is None:
                name = get_name_from_headers(dict(response.headers))

            if name is None:
                pass

            if isinstance(response, Error) or response.status != 200:
                return create_bad_url(db, url)

            # TODO: Should download_chunk_size not be related to token_size?
            chunked_response = response.content.iter_chunked(download_chunk_size)
            while True:
                if stop.is_set():
                    return None

                token = await rate_limiter.get(url.media_type)
                if token is None:
                    continue

                try:
                    chunk = await anext(chunked_response)
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    await asyncio.sleep(0.5)
                    continue

                if DEBUG_ASSERTS:
                    assert len(chunk) <= token.num_bytes

                await f.write(chunk)
                rate_limiter.return_token(token)

            rate_limiter.complete_url(course, url.media_type)

        print(f"Finished! {path}")
        return create_temp_url(db, config, url, download_url, name)

    except (ClientSSLError, ClientConnectorSSLError, ClientConnectorError, ClientConnectorCertificateError) as ex:
        logger.error(f"SSL Error downloading {url.url}: {type(ex)} {ex}")

        # TODO: Won't this crash eventually?
        # return await download_temp_file(db, session, rate_limiter, url, course, stop, priority, config, {})

    except (TimeoutError, ServerDisconnectedError) as ex:
        # TODO: Retry the download sometime later
        pass

    except Exception as ex:
        logger.error(f"Error downloading {url.url}: {type(ex)} {ex}\n\n{traceback.format_exc()}")

        raise

    # TODO: What does this mean?
    return None


# --- DownloadedURL ---

def read_downloaded_urls_to_dict(db: DatabaseSession) -> dict[int, list[DownloadedURL]]:
    final: DefaultDict[int, list[DownloadedURL]] = defaultdict(list)
    for it in db.execute(select(DownloadedURL)).scalars().all():
        final[it.course_id].append(it)

    return dict(final)


async def create_downloaded_urls(db: DatabaseSession, temp_files: list[TempURL], course_id: int, existing_media_containers: dict[int, list[DownloadedURL]], config: Config) -> list[DownloadedURL] | None:
    existing_containers = existing_media_containers.get(course_id, [])

    def to_downloaded_url(it: TempURL) -> dict[str, Any]:
        return {
            "url": it.url,
            "course_id": it.course_id,
            "version": it.version,

            "download_url": it.download_url,
            "name": it.name,
            "size": it.size,
            "checksum": it.checksum,
            "time_downloaded": it.time_downloaded,
        }

    # Remove the temporary files
    for file in temp_files:
        final = file.final_path(config)
        await aiofiles.os.makedirs(final.parent, exist_ok=True)

        file.temp_path(config).replace(final)
        db.delete(file)

    # TODO: Test if converting TempURLs into a dict is a performance hit
    return add_or_update_objects_to_database(
        db, {(it.url, it.course_id, it.version): it for it in existing_containers}, [to_downloaded_url(it) for it in temp_files], DownloadedURL, lambda it: (it["url"], it["course_id"], it["version"]),
        {it: it for it in DownloadedURL.__annotations__}, {}
    )
