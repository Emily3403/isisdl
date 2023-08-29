from __future__ import annotations

import asyncio
from collections import defaultdict
from json import JSONDecodeError
from typing import Any, Self

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.crud import parse_courses_from_API, read_downloadable_media_containers
from isisdl.api.models import AuthenticatedSession, Course, Error, MediaType, DownloadableMediaContainer
from isisdl.backend.models import User, Config
from isisdl.db_conf import add_or_update_objects_to_database
from isisdl.settings import isis_ignore, url_finder, extern_ignore, regex_is_isis_document
from isisdl.utils import datetime_fromtimestamp_with_None, normalize_url


# TODO: AJAX

class APIEndpoint:
    url = "https://isis.tu-berlin.de/webservice/rest/server.php"
    function: str

    @classmethod
    def new(cls) -> Self:
        return cls()
        pass

    @classmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | None = None, insert_into_output_payload: dict[str, Any] | None = None) -> Any | None:
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
                        if insert_into_output_payload is None:
                            return valid

                        # This is terrible ... I want to get rid of this solution and replace it with a conceptually better one, however I can't think of one currently.
                        if isinstance(valid, dict):
                            return valid | insert_into_output_payload

                        return insert_into_output_payload | {"it": valid}

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
        requests = [cls._get(session, data={"courseid": course.id}, insert_into_output_payload={"course_id": course.id}) for course in courses]

        new_data_with_duplicates = []

        # TODO: Performance benchmarks between asyncio.gather and asyncio.as_completed
        # TODO: Profile the parsing and maybe improve the runtime
        for _response in asyncio.as_completed(requests):
            response = await _response
            if response is None:
                continue

            course_id: int = response["course_id"]
            course_contents: list[dict[str, Any]] = response["it"]

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
                                            case {"fileurl": url, "type": file_type, "filepath": relative_path}:
                                                # if isis_ignore.match(url) is None and extern_ignore.match(url) is None:
                                                # Normalize attributes
                                                file["fileurl"] = normalize_url(url)
                                                file["filesize"] = file["filesize"] or None
                                                file["timecreated"] = file["timecreated"] or file["timemodified"]

                                                file["media_type"] = MediaType.extern
                                                file["course_id"] = course_id
                                                file["relative_path"] = (relative_path or "").lstrip("/")

                                                if file_type == "url":
                                                    file["media_type"] = MediaType.extern
                                                else:
                                                    file["media_type"] = MediaType.document

                                                new_data_with_duplicates.append(file)

                                            case _:
                                                pass

            # Now try to find as many urls as possible in the Course
            regex_url_matches = {normalize_url(url) for url in url_finder.findall(str(course_contents)) if isis_ignore.match(url) is None and extern_ignore.match(url) is None}
            for url in regex_url_matches:
                new_data_with_duplicates.append({
                    "fileurl": url, "course_id": course_id, "media_type": MediaType.document if regex_is_isis_document.match(url) is not None else MediaType.extern,
                    "relative_path": "", "filename": None, "filesize": None, "timecreated": None, "timemodified": None
                })

        # Remove the duplicate files
        maybe_duplicate_files = defaultdict(list)
        for file in new_data_with_duplicates:
            maybe_duplicate_files[(file["fileurl"], file["course_id"])].append(file)

        new_data = []
        for files in maybe_duplicate_files.values():
            if len(files) == 1:
                new_data.append(files[0])
                continue

            # TODO: This process is not necessarily deterministic. Make it as such
            new_data.append({
                "fileurl": files[0]["fileurl"], "course_id": files[0]["course_id"],
                "media_type": MediaType.document if any(file["media_type"] == MediaType.document for file in files) else MediaType.extern,
                "relative_path": next((relative_path for file in files if (relative_path := file["relative_path"])), ""),
                "filename": next((name for file in files if (name := file["filename"]) is not None), None),
                "filesize": next((name for file in files if (name := file["filesize"]) is not None), None),
                "timecreated": next((name for file in files if (name := file["timecreated"]) is not None), None),
                "timemodified": next((name for file in files if (name := file["timemodified"]) is not None), None),
            })

        existing_containers = {(it.course_id, it.url): it for it in read_downloadable_media_containers(db)}

        return add_or_update_objects_to_database(
            db, existing_containers, new_data, DownloadableMediaContainer, lambda x: (x["course_id"], x["fileurl"]),
            {"url": "fileurl", "course_id": "course_id", "media_type": "media_type", "relative_path": "relative_path",
             "name": "filename", "size": "filesize", "time_created": "timecreated", "time_modified": "timemodified"},
            {"url": normalize_url, "time_created": datetime_fromtimestamp_with_None, "time_modified": datetime_fromtimestamp_with_None}
        )


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
