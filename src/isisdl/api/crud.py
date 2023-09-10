from __future__ import annotations

import re
from base64 import standard_b64decode
from datetime import datetime
from typing import Any

from aiohttp import ClientSession as InternetSession
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.models import AuthenticatedSession, Course, DownloadableMediaContainer
from isisdl.backend.models import User, Config
from isisdl.db_conf import add_or_update_objects_to_database
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
        if response is None or str(response.url) == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            return None

        # Extract the session key
        text = await response.text()
        _session_key = re.search(r"\"sesskey\":\"(.*?)\"", text)
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
    existing_courses = {it.id: it for it in read_courses(db)}

    return add_or_update_objects_to_database(
        db, existing_courses, courses, Course, lambda course: course["id"],
        {"id": "id", "preferred_name": "shortname" if config.fs_course_default_shortname else "fullname", "short_name": "shortname", "full_name": "fullname",
         "number_users": "enrolledusercount", "is_favorite": "isfavourite", "time_of_last_access": "lastaccess", "time_of_last_modification": "timemodified", "time_of_start": "startdate", "time_of_end": "enddate"},
        {"time_of_last_access": datetime.fromtimestamp, "time_of_last_modification": datetime.fromtimestamp, "time_of_start": datetime.fromtimestamp, "time_of_end": datetime.fromtimestamp},
        {"preferred_name"}
    )


def read_courses(db: DatabaseSession) -> list[Course]:
    return list(db.execute(select(Course)).scalars().all())


def read_downloadable_media_containers(db: DatabaseSession) -> list[DownloadableMediaContainer]:
    return list(db.execute(select(DownloadableMediaContainer)).scalars().all())
