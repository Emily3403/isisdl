from typing import Any, Optional

import isisdl.bin.config as config
from isisdl.settings import is_windows


def assert_config_expected(username: Optional[str], clean_pw: Optional[str], encrypted_pw: Optional[str], filename_scheme: str, throttle_rate: Optional[int], update_policy: str,
                           telemetry: bool) -> None:
    items = {
        # TODO
        # username: config_helper.get_user(),
        # clean_pw: config_helper.get_clear_password(),
        # encrypted_pw: config_helper.get_encrypted_password(),
        # filename_scheme: config_helper.get_or_default_filename_scheme(),
        # throttle_rate: config_helper.get_throttle_rate(),
        # update_policy: config_helper.get_or_default_update_policy(),
        # telemetry: config_helper.get_telemetry(),
    }

    for a, b in items.items():
        assert b == a


def test_config_default(monkeypatch: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "d")

    config.main()

    # assert_config_expected(None, None, None, config_helper.default_filename_scheme(), None, config_helper.default_update_policy(), config_helper.default_telemetry())


def test_config_default_no_prompt(monkeypatch: Any) -> None:
    choices = iter(["", "2", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(choices))

    config.main()

    # assert_config_expected(None, None, None, config_helper.default_filename_scheme(), None, config_helper.default_update_policy(), config_helper.default_telemetry())


def test_config_input(monkeypatch: Any) -> None:
    if is_windows:
        choices = iter(["", "2", "1", "1", "55", "1", "0"])
    else:
        choices = iter(["", "2", "1", "0", "1", "55", "1", "0"])

    monkeypatch.setattr("builtins.input", lambda _: next(choices))

    config.main()

    assert_config_expected(None, None, None, "1", 55, "1", False)
