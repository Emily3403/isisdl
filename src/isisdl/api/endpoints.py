from __future__ import annotations

import asyncio
from abc import abstractmethod
from json import JSONDecodeError
from typing import Any, cast, TYPE_CHECKING

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.crud import parse_courses_from_API, read_media_urls, parse_videos_from_API, parse_documents_from_API
from isisdl.api.models import AuthenticatedSession, Course, Error, MediaURL
from isisdl.backend.models import User, Config
from isisdl.settings import DEBUG_ASSERTS, num_tries_download


# TODO:
#  - Rethink Ajax concept
#  - Make types for moodle object | list | None
#  - Better error handling (return None in production and raise if testing)


class APIEndpoint:
    url: str
    function: str

    @classmethod
    @abstractmethod
    def json_data(cls, session: AuthenticatedSession) -> dict[str, Any]:
        ...

    @classmethod
    @abstractmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | list[dict[str, Any]] | None = None) -> Any | None:
        ...

    @classmethod
    def enrich_data(cls, session: AuthenticatedSession, data: dict[str, Any] | list[dict[str, Any]] | None) -> dict[str, Any] | list[dict[str, Any]]:
        cls_data = cls.json_data(session)

        if data is None:
            return cls_data

        if isinstance(data, dict):
            data |= cls_data
            return data

        for it in data:
            it |= cls_data

        return data

    @classmethod
    async def _get_(cls, session: AuthenticatedSession, data: dict[str, Any] | list[dict[str, Any]], post_json: bool) -> Any | None:
        # response.json() may raise a TimeoutError, handle it gracefully
        for i in range(num_tries_download):
            async with session.post(cls.url, data, post_json) as response:

                if isinstance(response, Error) or not response.ok:
                    return None

                try:
                    match await response.json():
                        case {"errorcode": _} | {"exception": _}:
                            return None

                        case valid:
                            return valid

                except TimeoutError:
                    continue
                except JSONDecodeError:
                    return None
        return None


class MoodleAPIEndpoint(APIEndpoint):
    url = "https://isis.tu-berlin.de/webservice/rest/server.php"

    @classmethod
    def json_data(cls, session: AuthenticatedSession) -> dict[str, Any]:
        return {
            "moodlewssettingfilter": "true",
            "moodlewssettingfileurl": "true",
            "moodlewsrestformat": "json",
            "wsfunction": cls.function,
            "wstoken": session.api_token,
        }

    @classmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | list[dict[str, Any]] | None = None) -> Any | None:
        return await super()._get_(session, cls.enrich_data(session, data), post_json=False)


class AjaxAPIEndpoint(APIEndpoint):
    url = "https://isis.tu-berlin.de/lib/ajax/service.php"

    @classmethod
    def json_data(cls, session: AuthenticatedSession) -> dict[str, Any]:
        return {
            "methodname": cls.function,
        }

    @classmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | list[dict[str, Any]] | None = None) -> Any | None:
        for i in range(num_tries_download):
            async with session.get(cls.url, params={"sesskey": session.session_key}, json=cls.enrich_data(session, data)) as response:

                if isinstance(response, Error) or not response.ok:
                    return None

                try:
                    match await response.json():
                        case {"error": _} | {"errorcode": _} | {"exception": _}:
                            return None

                        case valid:
                            return valid

                except TimeoutError:
                    continue  # TODO: Somehow increment the timeout of .json()
                except JSONDecodeError:
                    return None
        return None


class VideoListAPI(AjaxAPIEndpoint):
    function = "mod_videoservice_get_videos"

    @classmethod
    async def get(cls, db: DatabaseSession, session: AuthenticatedSession, courses: list[Course], config: Config) -> Any:
        response = await super()._get(session, [{
            "args": {"courseid": course.id},
            "index": i
        } for i, course in enumerate(courses)])

        if response is None:
            return None

        return parse_videos_from_API(db, response, config)


class UserIDAPI(MoodleAPIEndpoint):
    function = "core_webservice_get_site_info"

    @classmethod
    async def get(cls, session: AuthenticatedSession) -> int | None:
        response = await cls._get(session)

        if response is None:
            return None

        return cast(int, response["userid"])


class UserCourseListAPI(MoodleAPIEndpoint):
    function = "core_enrol_get_users_courses"

    @classmethod
    async def get(cls, db: DatabaseSession, session: AuthenticatedSession, user: User, config: Config) -> list[Course] | None:
        # This could be a one-liner if python had the question mark operator: `parse_courses_from_API(db, await cls._get(session, data={"userid": user.user_id})?, config)`
        response: list[dict[str, Any]] | None = await cls._get(session, data={"userid": user.user_id})
        if response is None:
            return None

        return parse_courses_from_API(db, response, config)


class DocumentListAPI(MoodleAPIEndpoint):
    function = "core_course_get_contents"

    @classmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | list[dict[str, Any]] | None = None, post_json: bool = False) -> tuple[list[dict[str, list[dict[str, list[dict[str, Any]]]]]], int] | None:
        data = cls.enrich_data(session, data)

        if TYPE_CHECKING or DEBUG_ASSERTS:
            assert not isinstance(data, list)

        if "courseid" not in data:
            return None

        async with session.post(cls.url, data, post_json) as response:

            if isinstance(response, Error) or not response.ok:
                return None

            # TODO: Error handling
            return await response.json(), data["courseid"]

    @classmethod
    async def get(cls, db: DatabaseSession, session: AuthenticatedSession, courses: list[Course]) -> list[MediaURL]:
        requests = [cls._get(session, data={"courseid": course.id}) for course in courses]
        existing_documents = read_media_urls(db)
        all_documents = []

        for _response in asyncio.as_completed(requests):
            response = await _response
            if response is None:
                continue

            documents, course_id = response
            all_documents.extend(parse_documents_from_API(db, course_id, documents, existing_documents.get(course_id, {})))

        return all_documents


class CourseEnrollmentAPI(MoodleAPIEndpoint):
    function = "enrol_self_enrol_user"


class CourseUnEnrollmentAPI(MoodleAPIEndpoint):
    function = "enrol_self_unenrol_user"


class AssignmentAPI(MoodleAPIEndpoint):
    function = "mod_assign_get_assignments"

# TODO Content parsing:
#   - try out core_courseformat_get_state (ajax)
#   - unenrol_user_enrolment (together with the User Enrollment ID)


# API Flowchart
#
#  1. UserCourseListAPI (core_enrol_get_users_courses)
#    – We need a list of course ids to get the content from
#
#  2.
