from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session as DatabaseSession

from isisdl.api.endpoints import DocumentListAPI, VideoListAPI
from isisdl.api.models import MediaContainer, MediaURL, AuthenticatedSession, Course

__all__ = ["download_media_urls"]

from isisdl.backend.models import Config


async def gather_media_urls(db: DatabaseSession, session: AuthenticatedSession, courses: list[Course], config: Config) -> list[MediaURL]:
    urls = []
    for response in asyncio.as_completed([
        DocumentListAPI.get(db, session, courses),
        VideoListAPI.get(db, session, courses, config)
    ]):
        urls.extend(await response)

    return urls


async def download_media_urls(db: DatabaseSession, urls: list[MediaURL]) -> list[MediaContainer]:
    """
    - Figure out which containers need downloading
    - Resolve all conflicts in file paths
      - Develop an algorithm to deterministically sort files based on the optional attributes they have
      - Filter same download url
    - Try to figure out names / attributes from the URL
    - Figure out the order of downloading for the containers

    # To Integrate somewhere
    - Modify download_url based on urls, following Google Drive etc.

    """

    return []
