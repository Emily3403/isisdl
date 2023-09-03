from __future__ import annotations

import asyncio
from collections import defaultdict
from json import JSONDecodeError
from typing import Any, Self, cast

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.crud import parse_courses_from_API, read_downloadable_media_containers
from isisdl.api.models import AuthenticatedSession, Course, Error, MediaType, DownloadableMediaContainer
from isisdl.backend.models import User, Config
from isisdl.db_conf import add_or_update_objects_to_database
from isisdl.settings import isis_ignore, url_finder, extern_ignore, regex_is_isis_document
from isisdl.utils import datetime_fromtimestamp_with_None, normalize_url, flat_map


# TODO: AJAX

class APIEndpoint:
    url = "https://isis.tu-berlin.de/webservice/rest/server.php"
    function: str
    static_data = {
        "moodlewssettingfilter": "true",
        "moodlewssettingfileurl": "true",
        "moodlewsrestformat": "json",
    }

    @classmethod
    def new(cls) -> Self:
        return cls()
        pass

    @classmethod
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | None = None) -> Any | None:
        data = (data or {}) | cls.static_data | {
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

    @classmethod
    async def get(cls, session: AuthenticatedSession) -> int | None:
        response = await cls._get(session)

        if response is None:
            return None

        return cast(int, response["userid"])


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
    async def _get(cls, session: AuthenticatedSession, data: dict[str, Any] | None = None) -> tuple[list[dict[str, list[dict[str, list[dict[str, Any]]]]]], int] | None:
        data = (data or {}) | cls.static_data | {
            "wsfunction": cls.function,
            "wstoken": session.api_token,
        }

        if "courseid" not in data:
            return None

        async with session.post(cls.url, data) as response:

            if isinstance(response, Error) or not response.ok:
                return None

            return await response.json(), data["courseid"]

    @staticmethod
    def _normalize_file(file: dict[str, Any], url: str, course_id: int) -> dict[str, Any]:
        file["fileurl"] = normalize_url(url)
        file["filesize"] = file["filesize"] or None
        file["timecreated"] = file["timecreated"] or file["timemodified"]
        file["timemodified"] = file["timemodified"] or file["timecreated"]

        file_type = file.get("type", None)
        if file_type == "url":
            file["media_type"] = MediaType.extern
        else:
            file["media_type"] = MediaType.document

        file["course_id"] = course_id
        file["relative_path"] = (file.get("filepath") or "").lstrip("/")

        return file

    @staticmethod
    def _parse_files_from_regex(course_contents_str: str, course_id: int) -> list[dict[str, Any]]:
        all_files = []

        for url in url_finder.findall(course_contents_str):
            if isis_ignore.match(url) is not None or extern_ignore.match(url) is not None:
                continue

            all_files.append({
                "fileurl": url, "course_id": course_id, "media_type": MediaType.document if regex_is_isis_document.match(url) is not None else MediaType.extern,
                "relative_path": "", "filename": None, "filesize": None, "timecreated": None, "timemodified": None
            })

        return all_files

    @staticmethod
    def _filter_duplicates_from_files(duplicates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        maybe_duplicates = defaultdict(list)

        for duplicate in duplicates:
            maybe_duplicates[(duplicate["fileurl"], duplicate["course_id"])].append(duplicate)

        files_without_duplicates = []
        for files in maybe_duplicates.values():
            if len(files) == 1:
                files_without_duplicates.append(files[0])
                continue

            # TODO: This process is not necessarily deterministic. Make it as such
            files_without_duplicates.append({
                "fileurl": files[0]["fileurl"], "course_id": files[0]["course_id"],
                "media_type": MediaType.document if any(file["media_type"] == MediaType.document for file in files) else MediaType.extern,
                "relative_path": next((relative_path for file in files if (relative_path := file["relative_path"])), ""),
                "filename": next((name for file in files if (name := file["filename"]) is not None), None),
                "filesize": next((name for file in files if (name := file["filesize"]) is not None), None),
                "timecreated": next((name for file in files if (name := file["timecreated"]) is not None), None),
                "timemodified": next((name for file in files if (name := file["timemodified"]) is not None), None),
            })

        return files_without_duplicates

    @classmethod
    async def get(cls, db: DatabaseSession, session: AuthenticatedSession, courses: list[Course]) -> Any:
        requests = [cls._get(session, data={"courseid": course.id}) for course in courses]
        normalized_files_with_duplicates: list[dict[str, int | None | MediaType | str]] = []

        for _response in asyncio.as_completed(requests):
            response = await _response
            if response is None:
                continue

            course_contents, course_id = response
            # TODO: Profile if using a faster json parser is worth it

            files_to_filter: list[dict[str, Any]] = list(
                filter(
                    lambda it: it != {},

                    flat_map(
                        lambda it: it.get("contents", [{}]),
                        flat_map(
                            lambda it: it.get("modules", [{}]),
                            course_contents
                        )
                    )
                )
            )

            normalized_files_with_duplicates.extend(
                cls._normalize_file(file, url, course_id) for file in files_to_filter
                if (url := file.get("fileurl", None)) is not None and isis_ignore.match(url) is None and extern_ignore.match(url) is None
            )

            parsed_files_from_regex = cls._parse_files_from_regex(str(course_contents), course_id)
            normalized_files_with_duplicates.extend(parsed_files_from_regex)

        files = cls._filter_duplicates_from_files(normalized_files_with_duplicates)

        existing_containers = {(it.course_id, normalize_url(it.url)): it for it in read_downloadable_media_containers(db)}

        return add_or_update_objects_to_database(
            db, existing_containers, files, DownloadableMediaContainer, lambda x: (x["course_id"], normalize_url(x["fileurl"])),
            {"url": "fileurl", "course_id": "course_id", "media_type": "media_type", "relative_path": "relative_path",
             "name": "filename", "size": "filesize", "time_created": "timecreated", "time_modified": "timemodified"},
            {"url": normalize_url, "time_created": datetime_fromtimestamp_with_None, "time_modified": datetime_fromtimestamp_with_None}
        )

    @classmethod
    async def old_get(cls, db: DatabaseSession, session: AuthenticatedSession, courses: list[Course]) -> Any:
        requests = [cls._get(session, data={"courseid": course.id}) for course in courses]

        new_data_with_duplicates = []

        # TODO: Performance benchmarks between asyncio.gather and asyncio.as_completed
        # TODO: Profile the parsing and maybe improve the runtime
        for _response in asyncio.as_completed(requests):
            response = await _response
            if response is None:
                continue

            course_contents, course_id = response

            # Unfortunately, it doesn't seam as if python supports matching of nested dicts / lists
            for week in course_contents:
                match week:
                    case {"modules": modules}:
                        for module in modules:
                            match module:
                                case {"contents": files}:
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
