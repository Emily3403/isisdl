import os
import random
import shutil
import string
from pathlib import Path
from typing import Any, List, Dict, Set

from isisdl.backend.database_helper import DatabaseHelper
from isisdl.backend.downloads import MediaType
from isisdl.backend.request_helper import RequestHelper, PreMediaContainer, CourseDownloader, check_for_conflicts_in_files
from isisdl.utils import path, args, User, config, startup, database_helper
from isisdl.settings import database_file_location, lock_file_location, testing_download_sizes, env_var_name_username, env_var_name_password


def remove_old_files() -> None:
    for item in os.listdir(path()):
        if item != database_file_location and item != lock_file_location:
            shutil.rmtree(path(item))

    startup()
    config.__init__()  # type: ignore
    database_helper.__init__()  # type: ignore
    return


def test_remove_old_files() -> None:
    remove_old_files()


def test_database_helper(database_helper: DatabaseHelper) -> None:
    assert database_helper is not None
    database_helper.delete_file_table()
    database_helper.delete_config()

    assert all(bool(item) is False for item in database_helper.get_state().values())


def test_request_helper(request_helper: RequestHelper) -> None:
    assert request_helper is not None
    assert request_helper._instance is not None
    assert request_helper._instance_init is True
    assert request_helper.session is not None

    assert len(request_helper._courses) > 5
    assert len(request_helper.courses) > 5


def chop_down_size(pre_containers: List[PreMediaContainer]) -> Dict[MediaType, List[PreMediaContainer]]:
    possible: Dict[MediaType, List[PreMediaContainer]] = {MediaType.document: [], MediaType.extern: [], MediaType.video: []}

    for typ, lst in possible.items():
        containers = sorted([item for item in pre_containers if item.media_type == typ], key=lambda x: x.size)
        weights = [i for i, _ in enumerate(containers)]

        if not containers:
            continue

        while True:
            choice = random.choices(containers, weights, k=1)[0]

            if sum(item.size for item in lst) + choice.size > testing_download_sizes[typ.value]:
                break

            lst.append(choice)

    return possible


def get_content_to_download(request_helper: RequestHelper) -> List[PreMediaContainer]:
    known_bad_urls = {
        "https://befragung.tu-berlin.de/evasys/online.php?p=PCHVN",
        "https://cse.buffalo.edu/~rapaport/191/S09/whatisdiscmath.html",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/084bc9df893772381e602b3b1a81dc476426aa89d76e4ec507db78cbc2015489.mp4",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/13b1e775a69e8553ff195019f2fa7e560aa55018c482251f8bcab3e3ba715bca.mp4",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/490376af114fae8a5990ff539ac63e7476db8eb2094ea895536a88f3cfd756b1.mp4",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/519e4ed824da68f462f94e081ef3ab2cd728c5c6013803dcad526b4d1d41344b.mp4",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/b04d4f9fe73461083a82cc9892cc1a7674bb8fd97c540e31ce5def1d1d20e2a7.mp4",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/b946ddc66758a356e595fc5a6cb95a0d6ce7185276aff53de713f413c5a347c9.mp4",
        "https://isis.tu-berlin.de/mod/videoservice/file.php/d55a867aa37d0bbfd7f13ea1a746e033951417182d2f5ff33744c1b410ca6f73.mp4",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1484020/mod_resource/content/1/armv7-a-r-manual-VBAR-EXTRACT.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1664610/mod_resource/content/1/DS_HA_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_KOMPLETT.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Teil1_Kombinatorik.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Teil2_Zahlentheorie.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Teil3_Graphentheorie.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche01.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche02.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche03.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche04.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche05.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche06.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche07.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche08.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche09.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568350/mod_folder/content/24/Slides_Woche13.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt01.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt02_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt03_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt04_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt05_mit_L%C3%B6sungen%20%28updated%21%29.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt06_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt0708_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt09_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt10_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt11_mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1568351/mod_folder/content/20/Blatt12_%20mit_L%C3%B6sungen.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1587755/mod_resource/content/0/Blatt01.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1600738/mod_resource/content/1/Uebersicht_Woche_02.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1601203/mod_resource/content/1/Blatt02.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/10.FM.Aufgaben.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/11.%20FM.%20Aufgabe.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/11.%20FM.%20L%C3%B6sung.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/2.%20FM.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/3.%20FM.%20Tafel.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/4-5.FM.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/7.%20FM.Aufgabe.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/7.%20FM.L%C3%B6sung.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/8.%20FM.%20Aufgabe.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/8.%20FM.%20L%C3%B6sung.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1603847/mod_folder/content/9/9.FM.Aufgabe.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1609262/mod_resource/content/2/Blatt03.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1609264/mod_resource/content/1/Woche03.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1609322/mod_resource/content/0/Woche%2003.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1615712/mod_resource/content/0/Woche%204.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1615757/mod_resource/content/1/Blatt04.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1615760/mod_resource/content/2/Woche04.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1618455/mod_resource/content/8/Latex%20Vorlage.tex",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1622663/mod_resource/content/0/Woche%205.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1622781/mod_resource/content/1/Blatt05.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1622782/mod_resource/content/1/Woche05.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1628234/mod_resource/content/0/Woche%206.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1628286/mod_resource/content/1/Blatt06.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1628288/mod_resource/content/2/Woche06%20update.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche02_Do_10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche03%20Beamer%20Version_Do_10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche04%20Beamer%20Version_Tut3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche05_Ersatztut.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche06_Tut3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche07%20Beamer%20Version_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche08%20Beamer%20Version_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche09_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche10_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche11_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche12%20Beamer%20Version_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634522/mod_folder/content/15/Woche13%20Beamer%20Version_Do10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2010/Woche10_Tut.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2010/tut4_woche10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2011/DS_Tut_11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2011/tut4_woche11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2012/DS_Tut_12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2012/tut4_woche12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2013/DS_Tut13.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2013/Warshall.py.zip",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%2013/tut4_woche13.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%202/DS%20Woche%202%20Briefbeispiel.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%202/tut4_nachtrag_schubfach.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%202/tut4_woche2.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%203/DS03Tut04annotiert.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%203/tut4_woche3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%204/05_14_DS_Tut04.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%204/tut4_woche4.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%205/DSTUT5.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%205/sondertut_woche5.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%206/DS_6_TUT4.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%206/tut4_woche6.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%207/Woche7_Tut4.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%207/tut4_woche7.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%208/Woche8_Tut10-12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%208/Woche8_Tut12-14%20.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%208/tut4_woche8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%208/tutNeu10-12_woche8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%209/Woche9_Tut.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634524/mod_folder/content/29/Woche%209/tut4_woche9.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche02_Do_16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche03%20Beamer%20Version_Do_16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche04%20Beamer%20Version_Tut6.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche05_Ersatztut.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche06_ErsatzTut8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche07%20Beamer%20Version_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche08%20Beamer%20Version_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche09_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche10_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche11_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche12%20Beamer%20Version_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634525/mod_folder/content/11/Woche13%20Beamer%20Version_Do16.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%202/DS%20Woche%202%20Briefbeispiel.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%202/tut7_woche2.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%203/DS03Tut07annotiert.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%203/tut7_woche3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%204/05_14_DS_Tut07.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%204/tut7_woche4.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%205/DSTUT5.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%205/sondertut_woche5.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%206/DS_6_TUT7.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634526/mod_folder/content/9/Woche%206/tut7_woche6.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634527/mod_folder/content/3/Woche02_Mi_12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634527/mod_folder/content/3/Woche03%20Beamer%20Version_Mi_12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634527/mod_folder/content/3/Woche04%20Beamer%20Version_Tut8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634527/mod_folder/content/3/Woche05%20Beamer%20Version_Tut8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634527/mod_folder/content/3/Woche06_Tut8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634612/mod_resource/content/2/Woche07.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1634656/mod_resource/content/0/Woche%207.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche02_Mi_14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche03%20Beamer%20Version_Mi_14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche04%20Beamer%20Version_Tut3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche05%20Beamer%20Version_Tut1.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche06_Tut1.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche07%20Beamer%20Version_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche08%20Beamer%20Version_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche09_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche10_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche11_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche12%20Beamer%20Version_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1635559/mod_folder/content/14/Woche13%20Beamer%20Version_Mi14.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1636943/mod_resource/content/0/Blatt07.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1638358/mod_resource/content/0/W8.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1638457/mod_resource/content/1/Woche08.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1639446/mod_resource/content/1/Pr%C3%BCfungsleistung_HA.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1641450/mod_resource/content/2/LatexVorlage.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut%208%20A2.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut%208%20A3.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_1.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_2.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_3.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_4.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_5.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_6.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1642289/mod_folder/content/2/Tut9_7.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1643543/mod_resource/content/0/New%20Recording%209.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1643576/mod_resource/content/2/Blatt09.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1643577/mod_resource/content/1/Woche09.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_1.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_2.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_3.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_4.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_5.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_6.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_7.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1647162/mod_folder/content/1/Tut09_8.png",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1648266/mod_resource/content/1/Blatt10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1648274/mod_resource/content/1/Woche10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1648289/mod_resource/content/0/U%CC%88bersicht%20Woche%2010.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1653183/mod_resource/content/1/Blatt11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1653184/mod_resource/content/1/Woche11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1653253/mod_resource/content/0/Woche%2011.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1657410/mod_resource/content/1/Blatt12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1657418/mod_resource/content/1/Woche12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1657524/mod_resource/content/0/U%CC%88bersicht%20Woche%2012.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1661873/mod_resource/content/1/Woche13.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1661886/mod_resource/content/0/Woche%2013.m4a",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1867325/mod_folder/content/14/Bewertungsschema.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1867328/mod_folder/content/10/Bewertungsschema.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1867331/mod_folder/content/7/Bewertungsschema.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1877236/mod_folder/content/6/minified.py",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1877236/mod_folder/content/6/utils.py",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896123/mod_resource/content/5/online-tutorium-4.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896124/mod_resource/content/4/online-tutorium-4.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896149/mod_resource/content/10/online-tutorium-8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896164/mod_resource/content/12/online-tutorium-10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896165/mod_resource/content/10/online-tutorium-10.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896176/mod_resource/content/14/online-tutorium-12.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1896177/mod_resource/content/12/online-tutorium-11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1898221/mod_resource/content/3/lecture2.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1898222/mod_resource/content/10/lecture2.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1898236/mod_resource/content/12/lecture_LR.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1898237/mod_resource/content/7/lecture_LR.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1898255/mod_resource/content/13/lecture_Kernels.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1898256/mod_resource/content/4/lecture_Kernels.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1949036/mod_resource/content/1/online-tutorium-3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1951233/mod_folder/content/1/minified.py",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1951233/mod_folder/content/1/utils.py",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1956837/mod_folder/content/2/minified.py",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1956837/mod_folder/content/2/utils.py",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1962444/mod_resource/content/1/online-tutorium-5.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1966082/mod_resource/content/2/online-tutorium-6.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1967855/mod_resource/content/0/online-tutorium-3.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1970514/mod_resource/content/0/online-tutorium-5.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1970939/mod_resource/content/1/online-tutorium-7.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1978690/mod_resource/content/0/online-tutorium-9.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1978693/mod_resource/content/1/online-tutorium-6.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1978695/mod_resource/content/0/online-tutorium-7.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1981794/mod_resource/content/12/online-tutorium-8.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1985258/mod_resource/content/1/online-tutorium-11.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1985260/mod_resource/content/0/online-tutorium-9.pdf",
        "https://isis.tu-berlin.de/webservice/pluginfile.php/1995603/mod_resource/content/12/online-tutorium-12.pdf",
        "https://tu-berlin.hosted.exlibrisgroup.com/primo-explore/fulldisplay?docid=TN_springer_series978-3-540-46664-2&context=PC&vid=TUB&lang=de_DE&"
        "search_scope=TUB_ALL&adaptor=primo_central_multiple_fe&tab=tub_all&query=any,contains,Diskrete%20Strukturen&sortby=rank&offset=0https://flinga.fi/s/FLNWD7V",
        "https://www.bnv-bamberg.de/home/ba2636/catalanz.pdf",
        "https://www.mathsisfun.com/games/towerofhanoi.html",
    }

    files = [item for item in request_helper.download_content() if item.url not in known_bad_urls]
    conflict_free = chop_down_size(check_for_conflicts_in_files(files))

    return [item for row in conflict_free.values() for item in row]


def test_normal_download(request_helper: RequestHelper, database_helper: DatabaseHelper, user: User, monkeypatch: Any) -> None:
    args.num_threads = 4

    # Test without filename replacing
    config.filename_replacing = True
    request_helper.make_course_paths()

    content = get_content_to_download(request_helper)
    monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None, __=None: content)

    os.environ[env_var_name_username] = os.environ["ISISDL_ACTUAL_USERNAME"]
    os.environ[env_var_name_password] = os.environ["ISISDL_ACTUAL_PASSWORD"]
    CourseDownloader().start()

    # Now check if everything was downloaded successfully
    allowed_chars = set(string.ascii_letters + string.digits + ".")
    for container in content:
        assert os.path.exists(container.path)
        assert os.stat(container.path).st_size == container.size

        # The full path only consists of allowed chars
        assert all(c for item in Path(container.path).parts[1:] for c in item if c not in allowed_chars)

    prev_urls: Set[str] = set()
    container_mapping = {item.url: item for item in content}
    for item in database_helper.get_state()["fileinfo"]:
        url = item[1]

        if url in container_mapping:
            container = container_mapping[url]
            restored = PreMediaContainer.from_dump(item[1])
            assert item[8] is not None
            assert isinstance(restored, PreMediaContainer)
            assert restored.checksum is not None
            assert container == restored
            prev_urls.update(url)

        else:
            # Not downloaded (yet), checksum should be None.
            assert item[8] is None
    #
    # dupl = defaultdict(list)
    # for item in content:
    #     dupl[item.size].append(item)

    # not_downloaded = [item for row in dupl.values() for item in row if len(row) > 1]

    # TODO
    # for item in not_downloaded:
    #     try:
    #         prev_ids.remove(item.file_id)
    #     except KeyError:
    #         pass
    #
    # monkeypatch.setattr("builtins.input", lambda _=None: "n")
    # database_helper.delete_file_table()
    # restore_database_state(request_helper.download_content(), request_helper)
    #
    # # Now check if everything is restored (except `possible_duplicates`)
    # recovered_ids = {item[1] for item in database_helper.get_state()["fileinfo"]}
    #
    # assert prev_ids.difference(recovered_ids) == set()

# def sample_files(files: List[PreMediaContainer], num: int) -> List[Path]:
#     sizes = {item.size for item in files}
#     new_files = [item for item in Path(path()).rglob("*") if item.is_file() and item.stat().st_size in sizes]
#     random.shuffle(files)
#
#     return new_files[:num]
#
#
# def get_checksums_of_files(files: List[Path]) -> List[str]:
#     return [calculate_local_checksum(item) for item in files]
#
#
# def test_move_files(database_helper: DatabaseHelper, request_helper: RequestHelper, monkeypatch: Any) -> None:
#     content_to_download = get_content_to_download(request_helper)
#     monkeypatch.setattr("isisdl.backend.request_helper.RequestHelper.download_content", lambda _=None: content_to_download)
#     dupl = defaultdict(list)
#     for container in content_to_download:
#         dupl[container.size].append(container)
#
#     possible = [item for row in dupl.values() for item in row if len(row) == 1]
#
#     the_files = sample_files(possible, 10)
#     new_names = []
#     new_files = []
#     checksums = get_checksums_of_files(the_files)
#
#     for i, item in enumerate(the_files):
#         name, ext = os.path.splitext(item.name)
#         new_name = name + "_UwU" + ext
#         new_names.append(new_name)
#         new_files.append(os.path.join(item.parent, new_name))
#         item.rename(os.path.join(item.parent, new_name))
#
#     the_files.insert(0, Path("/home/emily/testisisdl/SoSe2021Algorithmentheorie/onlineTutorium2.pdf"))
#     monkeypatch.setattr("builtins.input", lambda _=None: "n")
#     database_helper.delete_file_table()
#     restore_database_state(request_helper.download_content(), request_helper)
#
#     for csum, new_name in zip(checksums, new_names):
#         assert database_helper.get_name_by_checksum(csum)
#
#     for file in new_files:
#         os.unlink(file)
#
#     database_helper.delete_file_table()
#     restore_database_state(request_helper.download_content(), request_helper)
#     delete_missing_files_from_database(request_helper)
#     for csum in checksums:
#         assert database_helper.get_name_by_checksum(csum) is None
