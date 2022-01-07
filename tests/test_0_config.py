from typing import Any, Tuple, Optional


import isisdl.bin.config as config
from isisdl.share.utils import config_helper


def assert_config_expected(user: Tuple[Optional[str], Optional[str]], filename_scheme: str, throttle_rate: Optional[int], update_policy: str, telemetry: str) -> None:
    items = {
        user: config_helper.get_user(),
        filename_scheme: config_helper.get_filename_scheme(),
        throttle_rate: config_helper.get_throttle_rate(),
        update_policy: config_helper.get_update_policy(),
        telemetry: config_helper.get_telemetry(),
    }

    for a, b in items.items():
        assert a == b


def test_config_default(monkeypatch: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "0")

    config.main()

    assert_config_expected((None, None), "0", None, "0", "1")


def test_config_default_no_prompt(monkeypatch: Any) -> None:
    choices = iter(["", "2", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _:  next(choices))

    config.main()

    assert_config_expected((None, None), "0", None, "0", "1")


def test_config_input(monkeypatch: Any) -> None:
    choices = iter(["2", "2", "2", "1", "0", "55", "0", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(choices))

    config.main()

    assert_config_expected((None, None), "1", 55, "2", "2")
