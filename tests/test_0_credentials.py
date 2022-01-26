import os
import random
import string
from typing import Tuple, Any

from isisdl.backend.crypt import get_credentials, encryptor
from isisdl.settings import env_var_name_username, env_var_name_password
from isisdl.backend.utils import config


def _generate_random_string() -> str:
    alphabet = string.digits + string.ascii_letters + string.punctuation
    return alphabet + "".join(random.choice(alphabet) for _ in range(32))


def generate_user() -> Tuple[str, str]:
    return _generate_random_string(), _generate_random_string()


backup_config = {}


def set_config(key, value):
    backup_config[key] = config[key]
    config[key] = value

def unset_config():
    for key in list(backup_config.keys()):
        config[key] = backup_config[key]
        del backup_config[key]

def do_get_credentials(username: str, password: str) -> None:
    user = get_credentials()

    assert user.username == username
    assert user.password == password


def test_environment_variables(monkeypatch: Any) -> None:
    username, password = generate_user()
    monkeypatch.setenv(env_var_name_username, username)
    monkeypatch.setenv(env_var_name_password, password)

    do_get_credentials(username, password)


def test_get_user_clean() -> None:
    username, password = generate_user()

    set_config("username", username)
    set_config("password", password)
    set_config("password_encrypted", False)

    do_get_credentials(username, password)

    unset_config()



def test_get_user_encrypted(monkeypatch: Any) -> None:
    username, password = generate_user()
    user_pass = _generate_random_string()
    stored_password = encryptor(user_pass, password)

    set_config("username", username)
    set_config("password", stored_password)
    set_config("password_encrypted", True)
    monkeypatch.setattr("getpass.getpass", lambda _: user_pass)

    do_get_credentials(username, password)

    unset_config()

def test_get_user_encrypted_bad_password(monkeypatch: Any) -> None:
    username, password = generate_user()
    user_pass = _generate_random_string()
    stored_password = encryptor(user_pass, password)

    set_config("username", username)
    set_config("password", stored_password)
    set_config("password_encrypted", True)
    responses = iter(["saltysalt", user_pass])
    monkeypatch.setattr("getpass.getpass", lambda _: next(responses))

    do_get_credentials(username, password)

    unset_config()



def test_manual_input(monkeypatch: Any) -> None:
    username, password = generate_user()

    monkeypatch.setattr("builtins.input", lambda _: username)
    monkeypatch.setattr("getpass.getpass", lambda _: password)

    do_get_credentials(username, password)
