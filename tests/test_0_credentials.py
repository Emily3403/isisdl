import random
import string
from typing import Tuple

from isisdl.backend.crypt import get_credentials


def generate_random_string() -> str:
    alphabet = string.digits + string.ascii_letters + string.punctuation
    return alphabet + "".join(random.choice(alphabet) for _ in range(32))


def generate_user() -> Tuple[str, str]:
    return generate_random_string(), generate_random_string()


def do_get_credentials(username: str, password: str) -> None:
    user = get_credentials()

    assert user.username == username
    assert user.password == password


# def test_environment_variables(monkeypatch: Any) -> None:
#     config.start_backup()
#
#     username, password = generate_user()
#     monkeypatch.setenv(env_var_name_username, username)
#     monkeypatch.setenv(env_var_name_password, password)
#
#     do_get_credentials(username, password)
#
#     config.restore_backup()
#
#
# def test_get_user_clean() -> None:
#     config.start_backup()
#
#     username, password = generate_user()
#     store_user(User(username, password))
#
#     do_get_credentials(username, password)
#
#     config.restore_backup()
#
#
# def test_get_user_encrypted(monkeypatch: Any) -> None:
#     config.start_backup()
#
#     username, password = generate_user()
#     additional_password = generate_random_string()
#     store_user(User(username, password), additional_password)
#
#     monkeypatch.setattr("getpass.getpass", lambda _=None: additional_password)
#
#     do_get_credentials(username, password)
#
#     config.restore_backup()


# def test_get_user_encrypted_bad_password(monkeypatch: Any) -> None:
#     config.start_backup()
#
#     username, password = generate_user()
#     additional_password = generate_random_string()
#     store_user(User(username, password), additional_password)
#
#     responses = iter(["salty$salt", additional_password])
#     monkeypatch.setattr("getpass.getpass", lambda _=None: next(responses))
#
#     do_get_credentials(username, password)
#
#     config.restore_backup()


# def test_manual_input(monkeypatch: Any) -> None:
#     username, password = generate_user()
#
#     monkeypatch.setattr("builtins.input", lambda _=None: username)
#     monkeypatch.setattr("getpass.getpass", lambda _=None: password)
#
#     do_get_credentials(username, password)
