import getpass
import os
import random
import string
from typing import Tuple

from isisdl.backend.crypt import get_credentials, store_clear, encryptor
from isisdl.share.settings import env_var_name_username, env_var_name_password, clear_password_file, encrypted_password_file, env_var_name_encrypted_password, already_prompted_file
from isisdl.share.utils import path, User


def generate_random_string(alphabet: str):
    return alphabet + "".join(random.choice(alphabet) for _ in range(32))


def generate_full_random_string():
    return generate_random_string(string.printable)


def generate_partial_random_string():
    return generate_random_string(string.printable[:96])


def do_get_credentials(random_username, random_password):
    user = get_credentials()

    assert user.username == random_username
    assert user.password == random_password


def setup_env_var() -> Tuple[str, str]:
    random_username, random_password = generate_full_random_string(), generate_full_random_string()

    os.environ[env_var_name_username] = random_username
    os.environ[env_var_name_password] = random_password

    return random_username, random_password


def cleanup_env_var():
    del os.environ[env_var_name_username]
    del os.environ[env_var_name_password]


def test_get_credentials_environment_variables():
    random_username, random_password = setup_env_var()

    do_get_credentials(random_username, random_password)

    cleanup_env_var()


def setup_clean_file() -> Tuple[str, str]:
    random_username, random_password = generate_partial_random_string(), generate_partial_random_string()

    user = User(random_username, random_password)
    store_clear(user)

    return random_username, random_password


def cleanup_clean_file():
    with open(path(clear_password_file), "w"):
        pass  # Erase the content


def test_get_credentials_clear_file():
    random_username, random_password = setup_clean_file()

    do_get_credentials(random_username, random_password)

    cleanup_clean_file()


def setup_encrypted_file() -> Tuple[str, str, str]:
    random_username, random_password = generate_full_random_string(), generate_full_random_string()

    password = generate_full_random_string()

    user = User(random_username, random_password)
    encryptor(password, user)

    return random_username, random_password, password


def cleanup_encrypted_file():
    os.remove(path(encrypted_password_file))


def test_get_credentials_encrypted_file(monkeypatch):
    random_username, random_password, password = setup_encrypted_file()

    monkeypatch.setattr(getpass, "getpass", lambda _: password)

    do_get_credentials(random_username, random_password)

    cleanup_encrypted_file()


def cleanup_encrypted_file_with_env_var():
    cleanup_encrypted_file()
    del os.environ[env_var_name_encrypted_password]


def test_get_credentials_encrypted_file_with_env_var(monkeypatch):
    random_username, random_password, password = setup_encrypted_file()

    os.environ[env_var_name_encrypted_password] = password

    do_get_credentials(random_username, random_password)

    cleanup_encrypted_file_with_env_var()


def test_get_credentials_input(monkeypatch):
    random_username, random_password = generate_full_random_string(), generate_full_random_string()

    monkeypatch.setattr("builtins.input", lambda _: random_username)
    monkeypatch.setattr(getpass, "getpass", lambda _: random_password)

    do_get_credentials(random_username, random_password)


def test_get_credentials_save_password(monkeypatch):
    random_username, random_password = setup_env_var()
    password = generate_full_random_string()

    os.remove(path(already_prompted_file))

    responses = iter([random_username, "y"])
    passwords = iter([random_password, password, password])

    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    monkeypatch.setattr("getpass.getpass", lambda _: next(passwords))

    do_get_credentials(random_username, random_password)

    cleanup_env_var()

    # Now, recover the information
    do_get_credentials(random_username, random_password)

    os.remove(path(encrypted_password_file))
