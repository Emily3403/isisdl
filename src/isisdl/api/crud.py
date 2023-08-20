from __future__ import annotations

import re
from logging import error
from typing import Any

from requests import Session as InternetSession
from requests.adapters import HTTPAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.models import AuthenticatedSession, MoodleMobileAdapter
from isisdl.backend.models import User, Config
from isisdl.settings import is_testing, discover_num_threads
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


def add_objects_to_database(db: DatabaseSession, it: list[Any]) -> list[Any] | None:
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


def authenticate_new_session(user: User, config: Config) -> AuthenticatedSession | None:
    session = InternetSession()

    session.mount("https://", HTTPAdapter(pool_maxsize=discover_num_threads // 2, pool_block=False))
    session.mount('moodlemobile://', MoodleMobileAdapter())
    session.headers.update({"User-Agent": f"isisdl (Python Requests) version {__version__}"})

    # First step of authenticating
    session.get("https://isis.tu-berlin.de/auth/shibboleth/index.php")
    session.post(
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

    # Second step
    session_key_response = session.post(
        "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
        params={"j_username": user.username, "j_password": user.decrypt_password(config), "_eventId_proceed": ""}
    )

    # Check if authentication succeeded
    if session_key_response is None or session_key_response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
        return None

    # Extract the session key
    session_key = re.search(r"\"sesskey\":\"(.*?)\"", session_key_response.text)
    if session_key is None:
        return None

    # Obtain the token
    token_response = session.get(
        "https://isis.tu-berlin.de/admin/tool/mobile/launch.php",
        params={"service": "moodle_mobile_app", "passport": "12345", "urlscheme": "moodledownloader"}
    )

    return AuthenticatedSession(session, session_key=session_key.group(1), api_token=token_response.text)
