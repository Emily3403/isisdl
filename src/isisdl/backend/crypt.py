import base64
import getpass
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from isisdl.settings import hash_algorithm, hash_length, hash_iterations, env_var_name_username, env_var_name_password
from isisdl.backend.utils import User, config_helper


def generate_key(password: str) -> bytes:
    # You might notice that the salt is empty. This is a deliberate decision.
    # In this scenario the encrypted file and password file are stored in the same directory.
    # Thus, if a hacker gains access they probably will have access to the salt file as well.

    # As the application is distributed on a local system basis the risc of a data-breach is comparatively low:
    # A hacker might only ever gain access to a single encrypted file.
    salt = b""

    kdf = PBKDF2HMAC(algorithm=hash_algorithm(), length=hash_length, salt=salt, iterations=hash_iterations)

    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encryptor(password: str, content: str) -> str:
    key = generate_key(password)
    return Fernet(key).encrypt(content.encode()).decode()


def decryptor(password: str, content: str) -> Optional[str]:
    key = generate_key(password)

    try:
        return Fernet(key).decrypt(content.encode()).decode()
    except InvalidToken:
        return None


def get_credentials() -> User:
    """
    Prioritizes:
        Environment variable > Database > Input
    """

    # First check the environment variables for username *and* password
    username, password = os.getenv(env_var_name_username), os.getenv(env_var_name_password)
    if username is not None and password is not None:
        return User(username, password)

    # Now query the database
    username = config_helper.get_user()
    clear_password = config_helper.get_clear_password()
    encrypted_password = config_helper.get_encrypted_password()

    if username is not None and clear_password is not None:
        return User(username, clear_password)

    if username is not None and encrypted_password is not None:
        user_password = getpass.getpass("Please enter the password you encrypted your password with: ")

        password = decryptor(user_password, encrypted_password)
        if password is None:
            print("Your password is incorrect. Please enter your login information manually (or restart me)!")
        else:
            return User(username, password)

    # If nothing is found prompt the user
    print("Please provide authentication for ISIS.")
    username = input("Username: ")
    password = getpass.getpass("Password: ")

    return User(username, password)
