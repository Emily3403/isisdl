# This settings file will get overwritten everytime a new version is installed.
# Don't overwrite any settings since you will have to manually edit this file everytime.
# Use the config file feature instead.

import os
import platform
import shutil
import sys
from collections import defaultdict
from hashlib import sha256
from http.client import HTTPSConnection
from linecache import getline
from typing import Any, DefaultDict

from cryptography.hazmat.primitives.hashes import SHA3_512
from yaml import safe_load, YAMLError

import isisdl.autorun

# The directory where everything lives in.

working_dir_location = os.path.join(os.path.expanduser("~"), "isisdl")

# The name of the SQLite Database
database_file_location = ".state.db"

current_database_version = 2

lock_file_location = ".lock"
enable_lock = True

error_directory_location = ".errors"

# --- Options for this executable ---
# Static settings
is_static = False

if is_static:
    isisdl_executable = os.path.realpath(sys.argv[0])
else:
    isisdl_executable = sys.executable

# A constant to detect if you are on Windows.
is_windows = platform.system() == "Windows"

# If the user has ffmpeg installed
has_ffmpeg = shutil.which("ffmpeg") is not None

# Check if being automatically run
is_autorun = sys.argv[0] == isisdl.autorun.__file__

# TODO: Add a setting for forcing characters to be ext4 / ntfs

error_text = "\033[1;91mError!\033[0m"

# -/- Options for this executable ---


# --- Checksum options ---

# All checksums are calculated with this algorithm
checksum_algorithm = sha256

# The number of bytes sampled per iteration to compute a checksum
checksum_num_bytes = 1024 * 4

# Skips $`checksum_base_skip` ^ i$ bytes per calculation → O(log(n)) time :O
checksum_base_skip = 2

# -/- Checksum options ---


# --- Password options ---

# This is what Django recommends as of January 2021
password_hash_algorithm = SHA3_512
password_hash_iterations = 390_000
password_hash_length = 32

# The password used to encrypt if no password is provided
master_password = "eeb36e726e3ffec16da7798415bb4e531bf8a57fbe276fcc3fc6ea986cb02e9a"

# -/- Password options ---

# --- Status options ---

# The number of spaces the first progress bar has
status_progress_bar_resolution = 50

# The number of spaces the second progress bar (for the downloads) has
download_progress_bar_resolution = 10

# Chop off the last ↓ characters of the status message for a ...
status_chop_off = 2

# The status message is replaced every ↓ seconds  (on Windows™ cmd it is *very* slow)
status_time = 0.1 if not is_windows else 0.75

# -/- Status options ---


# --- Download options ---

# Number of threads to discover video sizes
# TODO: Experiment with sizes
extern_discover_num_threads = 32

# Sets the chunk size for a download.
download_chunk_size = 2 ** 16

video_discover_download_size = 2 ** 8

# When ISIS is complaining that you are downloading too fast (Connection Aborted) ↓ s are waited.
sleep_time_for_isis = 3

# Will retry downloading an url ↓ times. If it fails, that MediaContainer will not get downloaded.
num_tries_download = 4

# Will fail a download if ISIS is not responding in
"""
for i in range(num_tries_download):
    download_timeout + download_timeout_multiplier ** (0.5 * i)
"""
download_timeout = 6
download_timeout_multiplier = 2

# -/- Download options ---


# --- Throttler options ---
# DownloadThrottler refresh rate in s
token_queue_refresh_rate = 0.01

# Collect the amount of handed out tokens in the last ↓ secs for measuring the bandwidth
token_queue_download_refresh_rate = 3

# When streaming, threads poll. This will get changed.
throttler_low_prio_sleep_time = 0.1


# -/- Throttler options ---

# --- FFMpeg options ---
# Options for the `--compress` feature
ffmpeg_args = ["-crf", "28", "-c:v", "libx265", "-c:a", "copy", "-preset", "superfast"]

# TODO: Document this
compress_duration_for_to_low_efficiency = 0.5
compress_minimum_stdev = 0.5
compress_score_mavg_size = 5
compress_std_mavg_size = 5
compress_minimum_score = 1.6
compress_insta_kill_score = 1.9
compress_duration_for_insta_kill = 0

# -/- FFMpeg options ---

# Options for the `--subscribe` feature
subscribed_courses_file_location = "subscribed_courses.json"
subscribe_courses_range = (24005, 24010)
subscribe_num_threads = 32

# --- Linux only feature options ---

# The path to the user-configuration directory. Linux only feature
config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "isisdl")

# The paths to the individual config files
config_file_location = os.path.join(config_dir_location, "config.yaml")
example_config_file_location = os.path.join(config_dir_location, "example.yaml")
export_config_file_location = os.path.join(config_dir_location, "export.yaml")

# The path to the systemd timer files. (Only supported on systemd-based linux)
systemd_dir_location = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
timer_file_location = os.path.join(systemd_dir_location, "isisdl.timer")
service_file_location = os.path.join(systemd_dir_location, "isisdl.service")


# -/- Linux only feature options ---


_testing_bad_urls = {
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


# Now load any options the user may overwrite (Linux exclusive)
def parse_config_file() -> DefaultDict[str, Any]:
    try:
        with open(config_file_location) as f:
            _dat = safe_load(f)
            if _dat is None:
                return defaultdict(lambda: None)

            if not isinstance(_dat, dict):
                raise YAMLError("Wrong type: is not a mapping")
            return defaultdict(lambda: None, _dat)

    except OSError:
        pass

    # Exception handling inspired by https://stackoverflow.com/a/30407093
    except YAMLError as ex:
        # Unfortunately mypy doesn't support this well...
        if hasattr(ex, "problem_mark") and hasattr(ex, "context") and hasattr(ex, "problem") and hasattr(ex, "context_mark"):
            assert hasattr(ex, "problem_mark")
            if ex.context is None:  # type: ignore
                where = str(ex.problem_mark)[4:]  # type: ignore
                offending_line = getline(config_file_location, ex.problem_mark.line).strip("\n")  # type: ignore
            else:
                where = str(ex.context_mark)[4:]  # type: ignore
                offending_line = getline(config_file_location, ex.context_mark.line).strip("\n")  # type: ignore

            print(f"Malformed config file: {where.strip()}\n")
            if ex.context is not None:  # type: ignore
                print(f"Error: {ex.problem} {ex.context}")  # type: ignore

            print(f"Offending line: \"{offending_line}\"\n")
        else:
            print(f"{error_text} the config file contains an error / is malformed.")
            print(f"The file is located at `{config_file_location}`\n")
            print(f"Reason: {ex}\n")

        print("I will be ignoring the specified configuration.\n")

    return defaultdict(lambda: None)


if not is_windows:
    data = parse_config_file()
    if data is not None:
        _globs = globals()
        for k, v in data.items():
            if k in _globs:
                _globs[k] = v


def check_online() -> bool:
    # Copied from https://stackoverflow.com/a/29854274
    conn = HTTPSConnection("8.8.8.8", timeout=5)
    try:
        conn.request("HEAD", "/")
        return True
    except Exception:
        return False
    finally:
        conn.close()


is_online = check_online()

# Check if the user is executing the library for the first time → .state.db should be missing
is_first_time = not os.path.exists(os.path.join(working_dir_location, database_file_location))

# Yes, changing behaviour when testing is evil. But I'm doing so in order to protect my `~/isisdl_downloads` directory.
is_testing = "pytest" in sys.modules
if is_testing:
    _working_dir_location = working_dir_location
    _config_dir_location = config_dir_location
    _config_file_location = config_file_location
    _example_config_file_location = example_config_file_location
    _export_config_file_location = export_config_file_location
    _status_time = status_time

    working_dir_location = os.path.join(os.path.expanduser("~"), "testisisdl")
    config_dir_location = os.path.join(os.path.expanduser("~"), ".config", "testisisdl")
    example_config_file_location = os.path.join(config_dir_location, "example.yaml")
    export_config_file_location = os.path.join(config_dir_location, "export.yaml")
    config_file_location = os.path.join(config_dir_location, "config.yaml")

    status_time = 1000000

# Environment variables are checked when authenticating
env_var_name_username = "ISISDL_USERNAME"
env_var_name_password = "ISISDL_PASSWORD"

# Should multithread be enabled? (Usually yes)
enable_multithread = True

global_vars = globals()

testing_download_sizes = {
    1: 1_000_000_000,  # Video
    2: 1_000_000_000,  # Documents
    3: 1_000_000_000  # Extern
}

# </ Test Options >
