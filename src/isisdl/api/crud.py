from __future__ import annotations

import re
from base64 import standard_b64decode
from datetime import datetime
from logging import error
from typing import Any

from aiohttp import ClientSession as InternetSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.models import AuthenticatedSession, Course
from isisdl.backend.models import User, Config
from isisdl.settings import is_testing
from isisdl.utils import T
from isisdl.version import __version__


def add_object_to_database(db: DatabaseSession, it: T) -> T | None:
    try:
        db.add(it)
        db.commit()
    except SQLAlchemyError as e:
        error(f"Inserting into the database failed: \"{e}\"")

        db.rollback()
        if is_testing:
            raise

        return None

    return it


def add_objects_to_database(db: DatabaseSession, it: list[T]) -> list[T] | None:
    try:
        db.add_all(it)
        db.commit()
    except SQLAlchemyError as e:
        error(f"Inserting into the database failed: \"{e}\"")

        db.rollback()
        if is_testing:
            raise

        return None

    return it


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
        if response is None or response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            return None

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


def parse_courses_from_API(db: DatabaseSession, courses: list[dict[str, Any]], config: Config) -> list[Course] | None:
    existing_courses = read_courses(db)
    all_courses = []

    for course in courses:
        maybe_course = existing_courses.get(course["id"])

        if maybe_course is None:
            the_course = Course(
                id=course["id"], preferred_name=course["shortname"] if config.fs_course_default_shortname else course["fullname"],
                short_name=course["shortname"], full_name=course["fullname"], number_users=course["enrolledusercount"], is_favorite=course["isfavourite"],
                time_of_last_access=datetime.fromtimestamp(course["lastaccess"]), time_of_last_modification=datetime.fromtimestamp(course["timemodified"]),
                time_of_start=datetime.fromtimestamp(course["startdate"]), time_of_end=datetime.fromtimestamp(course["enddate"]),
            )

            db.add(the_course)
            all_courses.append(the_course)

        else:
            maybe_course.short_name = course["shortname"]
            maybe_course.full_name = course["fullname"]
            maybe_course.number_users = course["enrolledusercount"]
            maybe_course.is_favorite = course["isfavourite"]
            maybe_course.time_of_last_access = datetime.fromtimestamp(course["lastaccess"])
            maybe_course.time_of_last_modification = datetime.fromtimestamp(course["timemodified"])
            maybe_course.time_of_start = datetime.fromtimestamp(course["startdate"])
            maybe_course.time_of_end = datetime.fromtimestamp(course["enddate"])
            db.add(maybe_course)
            all_courses.append(maybe_course)

    try:
        db.commit()
    except SQLAlchemyError as e:
        error(f"Inserting into the database failed: \"{e}\"")

        db.rollback()
        if is_testing:
            raise

        return None

    return all_courses


def read_courses(db: DatabaseSession) -> dict[int, Course]:
    return {it.id: it for it in db.execute(select(Course)).scalars().all()}
