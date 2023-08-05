from __future__ import annotations

import re
from logging import error
from typing import Any

from requests import Session as InternetSession
from requests.adapters import HTTPAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.models import AuthenticatedSession
from isisdl.backend.models import User
from isisdl.settings import is_testing, discover_num_threads
from isisdl.utils import generate_error_message


def add_object_to_database(db: DatabaseSession, it: Any) -> Any:
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


def authenticate_new_session(user: User) -> AuthenticatedSession | None:
    session = InternetSession()

    session.mount("https://", HTTPAdapter(pool_maxsize=discover_num_threads // 2, pool_block=False))
    session.headers.update({"User-Agent": "isisdl (Python Requests)"})

    try:
        session.get("https://isis.tu-berlin.de/auth/shibboleth/index.php?")
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

        response = session.post(
            "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s2",
            params={"j_username": user.username, "j_password": user.password, "_eventId_proceed": ""}
        )

        if response is None or response.url == "https://shibboleth.tubit.tu-berlin.de/idp/profile/SAML2/Redirect/SSO?execution=e1s3":
            # Credentials are wrong
            return None

        # Extract the session key
        key = re.search(r"\"sesskey\":\"(.*?)\"", response.text)
        if key is None:
            return None


    except Exception as ex:
        generate_error_message(ex)
