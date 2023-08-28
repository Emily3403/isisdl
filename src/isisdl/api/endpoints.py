from __future__ import annotations

import asyncio
from json import JSONDecodeError
from typing import Any, Self

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.crud import parse_courses_from_API
from isisdl.api.models import AuthenticatedSession, Course, Error
from isisdl.backend.models import User, Config
from isisdl.settings import isis_ignore, extern_ignore


# TODO: AJAX

class APIEndpoint:
    url = "https://isis.tu-berlin.de/webservice/rest/server.php"
    function: str

    @classmethod
    def new(cls) -> Self:
        return cls()
        pass

    @classmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | None = None) -> Any | None:
        data = (data or {}) | {
            "moodlewssettingfilter": "true",
            "moodlewssettingfileurl": "true",
            "moodlewsrestformat": "json",
            "wsfunction": cls.function,
            "wstoken": session.api_token,
        }

        async with session.post(cls.url, data) as response:

            if isinstance(response, Error) or not response.ok:
                return None

            try:
                match (x := await response.json()):
                    case {"errorcode": _} | {"exception": _}:
                        return None

                    case valid:
                        return valid

            except JSONDecodeError:
                return None


class UserIDAPI(APIEndpoint):
    function = "core_webservice_get_site_info"


class UserCourseListAPI(APIEndpoint):
    function = "core_enrol_get_users_courses"

    @classmethod
    async def get(cls, db: DatabaseSession, session: AuthenticatedSession, user: User, config: Config) -> list[Course] | None:
        response: list[dict[str, Any]] | None = await cls._get(session, data={"userid": user.user_id})
        if response is None:
            return None

        return parse_courses_from_API(db, response, config)


class CourseListAPI(APIEndpoint):
    # TODO: check out core_course_get_courses_by_field
    function = "core_course_search_courses"

    @classmethod
    async def get(cls, session: AuthenticatedSession) -> Any:
        return cls._get(session, data={"criterianame": "search", "criteriavalue": "", })


class TestAPI(APIEndpoint):
    function = "core_course_get_course_module"


class TestAjaxAPI(APIEndpoint):
    url = "https://isis.tu-berlin.de/lib/ajax/service.php"
    function = ""


class CourseContentsAPI(APIEndpoint):
    function = "core_course_get_contents"

    @classmethod
    async def get(cls, db: DatabaseSession, session: AuthenticatedSession, courses: list[Course]) -> Any:
        requests = [cls._get(session, data={"courseid": course.id}) for course in courses]

        # TODO: Performance benchmarks between asyncio.gather and asyncio.as_completed
        for response in asyncio.as_completed(requests):
            course_contents: list[dict[str, Any]] | None = await response
            if course_contents is None:
                continue

            # all_containers = []

            # Unfortunately, it doesn't seam as if python supports matching of nested dicts / lists
            for week in course_contents:
                match week:
                    case {"modules": modules}:
                        for module in modules:
                            match module:
                                case {"url": url, "contents": files}:
                                    if isis_ignore.match(url) is not None:
                                        continue

                                    for file in files:
                                        match file:
                                            case {"type": "url", "fileurl": url, "filepath": relative_path, "filename": name, "filesize": size, "timecreated": time_created, "timemodified": time_modified} \
                                                if isis_ignore.match(url) is None and extern_ignore.match(url) is None:
                                                pass

                                            case {"fileurl": url, "type": file_type, "filepath": relative_path, "filename": name, "filesize": size, "timecreated": time_created, "timemodified": time_modified}:
                                                pass
                                        pass

                pass

            pass

        await asyncio.sleep(2)

        return []


class CourseEnrollmentAPI(APIEndpoint):
    function = "enrol_self_enrol_user"


class CourseUnEnrollmentAPI(APIEndpoint):
    function = "enrol_self_unenrol_user"


class AssignmentAPI(APIEndpoint):
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
