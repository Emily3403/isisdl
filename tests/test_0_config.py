import random
import string
from typing import Any, Optional

from yaml import safe_load

from isisdl.backend.crypt import decryptor
from isisdl.backend.request_helper import RequestHelper
from isisdl.utils import config, User, export_config, startup
from isisdl.backend.config import authentication_prompt, update_policy_prompt, whitelist_prompt, filename_prompt, throttler_prompt
from isisdl.settings import export_config_file_location, master_password, env_var_name_username, env_var_name_password, is_windows


def generate_random_string() -> str:
    alphabet = string.digits + string.ascii_letters + string.punctuation
    return alphabet + "".join(random.choice(alphabet) for _ in range(32))


def assert_config_expected(
        password_encrypted: Optional[Any] = None,
        username: Optional[Any] = None,
        password: Optional[Any] = None,
        filename_replacing: Optional[Any] = None,
        throttle_rate: Optional[Any] = None,
        throttle_rate_autorun: Optional[Any] = None,
        update_policy: Optional[Any] = None,
        telemetry_policy: Optional[Any] = None,
        **_: Any) -> None:
    from isisdl.utils import config

    if password_encrypted is not None:
        assert config.password_encrypted == password_encrypted

    if username is not None:
        assert config.username == username

    if password is not None:
        assert config.password == password

    if filename_replacing is not None:
        assert config.filename_replacing == filename_replacing

    if throttle_rate is not None:
        assert config.throttle_rate == throttle_rate

    if throttle_rate_autorun is not None:
        assert config.throttle_rate_autorun == throttle_rate_autorun

    if update_policy is not None:
        assert config.update_policy == update_policy

    if telemetry_policy is not None:
        assert config.telemetry_policy == telemetry_policy


def test_config_export() -> None:
    if is_windows:
        return

    startup()
    export_config()

    with open(export_config_file_location) as f:
        exported_config = safe_load(f)

    assert_config_expected(**exported_config)


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

    authentication_prompt()

    assert config.username is None
    assert config.password is None  # type: ignore
    assert config.password_encrypted is None

    config.restore_backup()


def authentication_prompt_with_password(monkeypatch: Any, username: str, password: str, additional_password: str) -> None:
    choices = iter(["1", username])
    passwords = iter([password, additional_password, additional_password])
    monkeypatch.setattr("builtins.input", lambda _=None: next(choices))
    monkeypatch.setattr("isisdl.backend.config.getpass", lambda _=None: next(passwords))

    authentication_prompt()

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


def test_update_policy_prompt(monkeypatch: Any) -> None:
    config.start_backup()

    monkeypatch.setattr("builtins.input", lambda _=None: "2")
    config.update_policy = "notify_pip"
    update_policy_prompt()
    assert config.update_policy == "install_github"

    config.restore_backup()


def test_filename_prompt(monkeypatch: Any) -> None:
    config.start_backup()
    monkeypatch.setattr("builtins.input", lambda _=None: "1")

    config.filename_replacing = False
    try:
        del config._stored["filename_replacing"]
    except KeyError:
        pass

    filename_prompt()

    assert config.filename_replacing is True
    config.restore_backup()


def test_throttler_prompt(monkeypatch: Any) -> None:
    config.start_backup()
    choices = iter(["1", "42069"])
    monkeypatch.setattr("builtins.input", lambda _=None: next(choices))

    config.throttle_rate_autorun = -1
    throttler_prompt()

    assert config.throttle_rate_autorun == 42069
    config.restore_backup()


def test_whitelist_prompt_no(monkeypatch: Any) -> None:
    config.start_backup()
    monkeypatch.setattr("builtins.input", lambda _=None: "0")

    config.whitelist = [42, 69]
    whitelist_prompt()

    assert config.whitelist is None
    config.restore_backup()  # type: ignore


def test_whitelist_prompt(monkeypatch: Any, user: User, request_helper: RequestHelper) -> None:
    config.start_backup()
    monkeypatch.setenv(env_var_name_username, user.username)
    monkeypatch.setenv(env_var_name_password, user.password)

    indexes = [item.course_id for item in request_helper.courses[:5]]
    choices = iter(["1", ",".join(str(item) for item in indexes)])
    monkeypatch.setattr("builtins.input", lambda _=None: next(choices))

    whitelist_prompt()
    assert set(config.whitelist or []) == set(indexes)

    config.restore_backup()
    request_helper.get_courses()
