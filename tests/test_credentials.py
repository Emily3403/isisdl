# import pytest
# import io
import os
import random
import string

from isis_dl.backend.crypt import get_credentials  # , store_clear, encryptor
from isis_dl.share.settings import env_var_name_username, env_var_name_password  # , clear_password_file, encrypted_password_file


# from isis_dl.share.utils import path, User


def test_get_credentials_environment_variables():
    random_username = "".join(random.choice(string.printable) for _ in range(16))
    random_password = "".join(random.choice(string.printable) for _ in range(16))

    os.environ[env_var_name_username] = random_username
    os.environ[env_var_name_password] = random_password

    user = get_credentials()

    assert user.username == random_username
    assert user.password == random_password

    del os.environ[env_var_name_username]
    del os.environ[env_var_name_password]

# def test_get_credentials_clear_file():
#     random_username = "".join(random.choice(string.printable) for _ in range(16))
#     random_password = "".join(random.choice(string.printable) for _ in range(16))
#
#     user = User(random_username, random_password)
#     store_clear(user)
#
#     user = get_credentials()
#
#     assert user.username == random_username
#     assert user.password == random_password
#
#     with open(path(clear_password_file), "w") as f:
#         pass  # Erase the content

# def test_get_credentials_encrypted_file(monkeypatch):
#     random_username = "".join(random.choice(string.printable) for _ in range(16))
#     random_password = "".join(random.choice(string.printable) for _ in range(16))
#     password = "".join(random.choice(string.printable) for _ in range(16))
#
#     user = User(random_username, random_password)
#     encryptor(password, user)
#
#     stdin = io.StringIO('my input')
#     stdin.write(password + "\n")
#     monkeypatch.setattr('sys.stdin', stdin)
#     new_user = get_credentials()
#
#     os.remove(path(encrypted_password_file))
#
#     print()
#
#
