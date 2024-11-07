#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Union, Dict, Any, Set, DefaultDict, Tuple

import matplotlib.pyplot as plt
from distlib.version import LegacyVersion
from distutils.version import Version

from isisdl.server.server_settings import server_path, log_dir_location, log_type, log_dir_version, graph_dir_location


# TODO:
#   Users over time → moving average window / first time registered.
#   Different OS versions

@dataclass
class Data:
    username: str
    OS: str
    OS_spec: str
    version: LegacyVersion | Version

    time: datetime
    is_first_time: bool
    num_g_files: int
    num_c_files: int
    total_g_bytes: int
    total_c_bytes: int
    course_ids: List[int]
    config: dict[str, bool | str | int | None | dict[int, str]]

    @classmethod
    def from_json(cls, info: Dict[str, Any]) -> Data:
        obj = cls(**info)
        the_time: int = obj.time  # type: ignore
        obj.time = datetime.fromtimestamp(the_time)

        return obj


@dataclass
class DataV1(Data):
    pass


@dataclass
class DataV2(DataV1):
    is_static: bool


@dataclass
class Data3Bad(DataV2):
    current_database_version: int
    has_ffmpeg: bool
    forbidden_chars: List[int]
    fstype: str


@dataclass
class DataV3(DataV2):
    database_version: int
    has_ffmpeg: bool
    forbidden_chars: List[int]
    fstype: str


# @dataclass
# class DataV4(DataV3):
#     message: str


def get_data() -> List[Data]:
    def get_Data_subclasses() -> Set[Any]:
        # Copied from https://stackoverflow.com/a/5883218
        subclasses = set()
        work = [Data]
        while work:
            parent = work.pop()
            for child in parent.__subclasses__():
                if child not in subclasses:
                    subclasses.add(child)
                    work.append(child)

        return subclasses

    content: List[Data] = []
    for date in server_path.joinpath(log_dir_location, log_dir_version, log_type).glob("*"):
        for file in date.glob("*"):
            with file.open() as f:
                text = f.read()

                for data_type in sorted(get_Data_subclasses(), key=lambda it: it.__doc__[:6]):  # type: ignore[no-any-return]
                    try:
                        data = data_type.from_json(json.loads(text))
                        break
                    except TypeError:
                        pass
                else:
                    assert False, "Could not find a datatype suitable for containig this log. Aborting!"

                content.append(data)

    sort = defaultdict(list)
    for item in content:
        sort[item.__class__].append(item)

    return content


def analyze_versions() -> None:
    data = get_data()
    versions: Dict[str, Tuple[Union[LegacyVersion, Version], datetime]] = {}

    for dat in data:
        if datetime.now() - dat.time < timedelta(days=30):
            versions[dat.username] = (dat.version, dat.time)

    perc_versions = []
    labels = []
    all_versions = [it for it, _ in versions.values()]

    for version in set(all_versions):
        perc_versions.append(all_versions.count(version))
        labels.append(str(version))

    plt.title("Distribution of versions for isisdl")
    plt.pie(perc_versions, labels=labels)
    plt.tight_layout()
    plt.savefig(server_path.joinpath(log_dir_location, log_dir_version, graph_dir_location, "versions.png"))
    plt.show()

    print("===== Version Analysis =====")
    print(json.dumps({k: (v, str(a)) for k, (v, a) in versions.items()}, indent=4))
    print("==/== Version Analysis =====")


def analyze_users_per_day() -> None:
    data = get_data()
    users: DefaultDict[str, int] = defaultdict(int)
    counted: Set[str] = set()

    for dat in data:
        if dat.time.strftime("%y-%m-%d ") + dat.username in counted:
            continue

        counted.add(dat.time.strftime("%y-%m-%d ") + dat.username)
        users[dat.time.strftime("%y-%m-%d")] += 1

    plt.title("Users over time for isisdl")
    plt.figure(dpi=300)
    plt.xticks(rotation=90)
    plt.plot(list(users.keys()), list(users.values()))
    plt.tight_layout()
    plt.show()
    plt.savefig(server_path.joinpath(log_dir_location, log_dir_version, graph_dir_location, "users_per_day.png"))


def analyze_different_users_per_day() -> None:
    data = get_data()
    users: DefaultDict[str, int] = defaultdict(int)
    counted: Set[str] = set()

    for dat in data:
        if dat.time.strftime("%y-%m-%d ") + dat.username in counted:
            continue

        counted.add(dat.time.strftime("%y-%m-%d ") + dat.username)
        users[dat.time.strftime("%y-%m-%d")] += 1

    plt.title("Users over time for isisdl")
    plt.figure(dpi=300)
    plt.xticks(rotation=90)
    plt.plot(list(users.keys()), list(users.values()))
    plt.tight_layout()
    plt.show()
    plt.savefig(server_path.joinpath(log_dir_location, log_dir_version, graph_dir_location, "users_per_day.png"))


def analyze_new_users_over_time() -> None:
    data = get_data()

    users: DefaultDict[str, int] = defaultdict(int)
    counted: Set[str] = set()

    for dat in data:
        if dat.username in counted:
            continue

        counted.add(dat.username)
        users[dat.time.strftime("%y-%m-%d")] += 1

    # keys = set(users.keys())
    # for key in users.keys():
    #     i = 0

    print()
    pass


def analyze_config() -> None:
    data = get_data()

    users: DefaultDict[str, List[Any]] = defaultdict(list)
    counted: Set[str] = set()

    for dat in data:
        if not isinstance(dat, DataV3):
            pass

        counted.add(dat.username)
        for k, v in dat.config.items():
            users[f"{k} {dat.username}"].append(v)

    for k, val in users.items():
        if all(it == val[0] for it in val):
            users[k] = val[0]

    final = {k: v for k, v in sorted(users.items(), key=lambda item: item[0])}

    print(final)
    pass


def remove_bad_files() -> None:
    for file in server_path.joinpath(log_dir_location, log_dir_version).rglob("*"):
        try:
            data = json.loads(file.read_text())
            if "config" not in data or data["username"] is None:
                file.unlink()

        except Exception:
            pass


def main() -> None:
    # remove_bad_files()
    # analyze_new_users_over_time()

    # analyze_versions()
    # analyze_users_per_day()
    analyze_config()
    return


if __name__ == '__main__':
    main()
