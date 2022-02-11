import random
import string
from typing import Any

from yaml import safe_load

import isisdl.bin.config as config_run
from isisdl.backend.crypt import decryptor
from isisdl.backend.request_helper import RequestHelper
from isisdl.backend.utils import config, User
from isisdl.settings import export_config_file_location, master_password, env_var_name_username, env_var_name_password, is_windows


def generate_random_string() -> str:
    alphabet = string.digits + string.ascii_letters + string.punctuation
    return alphabet + "".join(random.choice(alphabet) for _ in range(32))


def assert_config_expected(password_encrypted: Any, username: Any, password: Any, filename_replacing: Any, throttle_rate: Any, throttle_rate_autorun: Any,
                           update_policy: Any, telemetry_policy: Any, **_: Any) -> None:
    from isisdl.backend.utils import config

    assert config.password_encrypted == password_encrypted
    assert config.username == username
    assert config.password == password
    assert config.filename_replacing == filename_replacing
    assert config.throttle_rate == throttle_rate
    assert config.throttle_rate_autorun == throttle_rate_autorun
    assert config.update_policy == update_policy
    assert config.telemetry_policy == telemetry_policy


def test_config_export(monkeypatch: Any) -> None:
    if is_windows:
        return

    monkeypatch.setattr("builtins.input", lambda _=None: "e")
    config_run.main()

    with open(export_config_file_location) as f:
        exported_config = safe_load(f)

    assert_config_expected(username=config.username, password=config.password, password_encrypted=config.password_encrypted, **exported_config)


def test_config_backup() -> None:
    current_config = config.to_dict()
    config.start_backup()

    config.password = "1"
    config.throttle_rate = 4
    config.telemetry_policy = not config.telemetry_policy

    config.restore_backup()
    assert_config_expected(**current_config)
    assert config.password != "1"


def test_config_authentication_prompt_no(monkeypatch: Any) -> None:
    config.start_backup()
    monkeypatch.setattr("builtins.input", lambda _=None: "0")

    config.username = "hello"
    config.password = "world"
    config.password_encrypted = False

    config_run.authentication_prompt()

    assert config.username is None
    assert config.password is None  # type: ignore
    assert config.password_encrypted is None

    config.restore_backup()


def authentication_prompt_with_password(monkeypatch: Any, username: str, password: str, additional_password: str) -> None:
    choices = iter(["1", username])
    passwords = iter([password, additional_password, additional_password])
    monkeypatch.setattr("builtins.input", lambda _=None: next(choices))
    monkeypatch.setattr("isisdl.bin.config.getpass", lambda _=None: next(passwords))

    config_run.authentication_prompt()

    assert config.username == username
    assert config.password is not None
    assert config.password_encrypted is bool(additional_password)

    restored_password = decryptor(additional_password or master_password, config.password)
    assert restored_password == password


def test_config_authentication_prompt_no_pw(monkeypatch: Any, user: User) -> None:
    config.start_backup()
    authentication_prompt_with_password(monkeypatch, user.username, user.password, "")
    config.restore_backup()


def test_config_authentication_prompt_with_pw(monkeypatch: Any, user: User) -> None:
    config.start_backup()
    authentication_prompt_with_password(monkeypatch, user.username, user.password, generate_random_string())
    config.restore_backup()


def test_whitelist_prompt_no(monkeypatch: Any) -> None:
    config.start_backup()
    monkeypatch.setattr("builtins.input", lambda _=None: "0")

    config.whitelist = [42, 69]
    config_run.whitelist_prompt()

    assert config.whitelist is None
    config.restore_backup()  # type: ignore


def test_whitelist_prompt(monkeypatch: Any, user: User, request_helper: RequestHelper) -> None:
    config.start_backup()
    monkeypatch.setenv(env_var_name_username, user.username)
    monkeypatch.setenv(env_var_name_password, user.password)

    prev_courses = request_helper.courses.copy()
    indexes = [0, 3, 5]
    choices = iter(["1", ",".join(str(item) for item in indexes)])
    monkeypatch.setattr("builtins.input", lambda _=None: next(choices))

    config_run.whitelist_prompt()

    should_be_chosen = [prev_courses[i].course_id for i in indexes]

    assert should_be_chosen == config.whitelist
    config.restore_backup()
