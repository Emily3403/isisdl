import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List

import isis_dl.bin.build_checksums as build_checksums
from isis_dl.backend.api import CourseDownloader, AlmostMediaContainer
from isis_dl.backend.downloads import MediaContainer, DownloadStatus, FailedDownload, MediaType
from isis_dl.share.settings import num_sessions, checksum_file
from isis_dl.share.utils import path, CriticalError

try:
    from conftest import make_dl
except ImportError:
    from .conftest import make_dl

num_threads = 4

taken_urls: List[AlmostMediaContainer] = []


def make_files():
    max_num = 100
    num_zip = 10
    num_pdf = 10

    num_videos = 10  # take the 10 smallest

    # Figure out sizes
    other, pdfs, zips, videos = [], [], [], []

    def preselect():
        return [item for item in CourseDownloader.not_inst_files if item not in taken_urls]

    def fig_out(item: AlmostMediaContainer):
        if item.is_video:
            info = MediaContainer.extract_info_from_header(item.s, item.arg["url"])  # type: ignore
            if info is None:
                raise CriticalError

            a, *_ = info
            if a is None:
                raise CriticalError

            item.size = a

            videos.append(item)

        elif "mod/folder" in item.arg:
            zips.append(item)

        elif "mod/resource" in item.arg:
            pdfs.append(item)

        else:
            other.append(item)

    with ThreadPoolExecutor(32) as ex:
        list(ex.map(fig_out, preselect()[:max_num]))

    def make_list(lst, num):
        try:
            return random.sample(lst, k=num)
        except ValueError:
            return lst

    pdfs = make_list(pdfs, num_pdf)
    zips = make_list(zips, num_zip)
    videos = sorted(videos, key=lambda x: x.size)[:num_videos]

    global taken_urls
    if not taken_urls:
        taken_urls = pdfs + zips + other + videos

    CourseDownloader.not_inst_files = taken_urls


def download_course_downloader(dl):
    dl.authenticate_all()
    assert len(CourseDownloader.sessions) == num_sessions

    dl.find_courses()
    assert len(CourseDownloader.courses) > 0

    dl.build_file_list()

    make_files()

    dl.build_checksums()
    assert len(CourseDownloader.files) >= 0
    dl.check_for_conflicts_in_files()

    with ThreadPoolExecutor(num_threads) as ex:
        list(ex.map(lambda x: x.download(), CourseDownloader.files))  # type: ignore


def test_course_downloader():
    dl = make_dl()

    download_course_downloader(dl)

    dl.finish()


def test_course_downloader_again():
    dl = make_dl()

    download_course_downloader(dl)

    dl.finish()

    for item in CourseDownloader.files:
        assert isinstance(item.status, FailedDownload) or item.status == DownloadStatus.found_by_checksum


def test_build_checksums():
    # Delete all checksum files
    for file in Path(path()).rglob(checksum_file):
        file.unlink()

    build_checksums.main()

    dl = make_dl()

    download_course_downloader(dl)

    dl.finish()

    for item in CourseDownloader.files:
        if item.media_type == MediaType.archive:
            continue

        assert isinstance(item.status, FailedDownload) or item.status == DownloadStatus.found_by_checksum
