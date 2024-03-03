from __future__ import annotations

import re
from base64 import standard_b64decode
from collections import defaultdict
from html import unescape
from itertools import chain
from typing import Any, Literal, cast, DefaultDict

from aiohttp import ClientSession as InternetSession
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.models import AuthenticatedSession, Course, MediaURL, MediaType, NormalizedDocument
from isisdl.backend.models import User, Config
from isisdl.db_conf import add_or_update_objects_to_database
from isisdl.settings import url_finder, isis_ignore, extern_ignore, regex_is_isis_document, regex_is_isis_video
from isisdl.utils import datetime_fromtimestamp_with_None, flat_map
from isisdl.version import __version__


async def authenticate_new_session(user: User, config: Config) -> AuthenticatedSession | None:
    session = InternetSession(headers={"User-Agent": f"isisdl (Python aiohttp) version {__version__}"})

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
        {it: it for it in NormalizedDocument.__annotations__.keys()},
        {"time_created": datetime_fromtimestamp_with_None, "time_modified": datetime_fromtimestamp_with_None},
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
        "time_created": file.get("timecreated") or file.get("timemodified"),
        "time_modified": file.get("timemodified") or file.get("timecreated"),
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

    def resolve_conflict(attr: Literal["url", "course_id", "media_type", "relative_path", "name", "size", "time_created", "time_modified"]) -> Any:
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
        "time_created": resolve_conflict("time_created"),
        "time_modified": resolve_conflict("time_modified"),
    }


# --- Videos ---


def create_videos_from_API(db: DatabaseSession, videos: list[dict[str, Any]], course_id: int, existing_videos: dict[str, MediaURL]) -> list[MediaURL] | None:
    # Filter out duplicate videos
    videos = list({video["url"]: video for video in videos}.values())

    videos = list(map(lambda it: it | {"course_id": course_id, "media_type": MediaType.video, "relative_path": "Videos", "size": None, "time_modified": None}, videos))

    return add_or_update_objects_to_database(
        db, existing_videos, videos, MediaURL, lambda video: video["url"],
        {"url": "url", "course_id": "course_id", "media_type": "media_type", "relative_path": "relative_path", "name": "collectionname", "size": "size", "time_created": "timecreated", "time_modified": "time_modified"},
        {"time_created": datetime_fromtimestamp_with_None, "time_modified": datetime_fromtimestamp_with_None},
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
