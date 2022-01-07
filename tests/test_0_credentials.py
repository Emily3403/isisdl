import os
import random
import string
from typing import Tuple, Any

from isisdl.backend.crypt import get_credentials, encryptor
from isisdl.share.settings import env_var_name_username, env_var_name_password
from isisdl.share.utils import config_helper


def _generate_random_string() -> str:
    alphabet = string.digits + string.ascii_letters + string.punctuation
    return alphabet + "".join(random.choice(alphabet) for _ in range(32))


def generate_user() -> Tuple[str, str]:
    return _generate_random_string(), _generate_random_string()


def do_get_credentials(username: str, password: str) -> None:
    user = get_credentials()

    assert user.username == username
    assert user.password == password


def test_environment_variables(monkeypatch: Any) -> None:
    """
    Verifies that the environment is capable of handling all ascii characters
    """

    username, password = generate_user()
    os.environ[env_var_name_username] = username
    os.environ[env_var_name_password] = password

    do_get_credentials(username, password)

    del os.environ[env_var_name_username]
    del os.environ[env_var_name_password]


def test_get_user_clean() -> None:
    username, password = generate_user()
    config_helper.set_user(username, password)

    do_get_credentials(username, password)

    config_helper.delete_config()


def test_get_user_encrypted(monkeypatch: Any) -> None:
    username, password = generate_user()

    user_pass = _generate_random_string()
    enc_password = encryptor(user_pass, password)

    config_helper.set_user(username, enc_password)

    monkeypatch.setattr("getpass.getpass", lambda _: user_pass)

    do_get_credentials(username, password)

    config_helper.delete_config()


def test_manual_input(monkeypatch: Any) -> None:
    username, password = generate_user()

    monkeypatch.setattr("builtins.input", lambda _: username)
    monkeypatch.setattr("getpass.getpass", lambda _: password)

    do_get_credentials(username, password)
