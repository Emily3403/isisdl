import base64
import os
import pickle
import getpass
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from isisdl.share.settings import hash_algorithm, hash_length, hash_iterations, clear_password_file, encrypted_password_file, \
    env_var_name_username, env_var_name_password, env_var_name_encrypted_password
from isisdl.share.utils import User, path, args, logger


def generate_key(password: str) -> bytes:
    # You might notice that the salt is empty. This is a deliberate decision.
    # In this scenario the encrypted file and password file are stored in the same directory.
    # Thus, if a hacker gains access they probably will have access to the salt file as well.

    # As the application is distributed on a local system basis the risc of a data-breach is comparatively low:
    # A hacker might only ever gain access to a single encrypted file.
    salt = b""

    kdf = PBKDF2HMAC(algorithm=hash_algorithm, length=hash_length, salt=salt, iterations=hash_iterations)

    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def store_clear(user: User) -> None:
    with open(path(clear_password_file), "w") as f:
        f.write(user.dump())


def encryptor(password: str, obj: object) -> bytes:
    key = generate_key(password)
    return Fernet(key).encrypt(pickle.dumps(obj))


def decryptor(password: str) -> Optional[User]:
    try:
        with open(path(encrypted_password_file), "rb") as f:
            content = f.read()

    except OSError:
        logger.debug(f"The encrypted file {encrypted_password_file} was not found. It should have been checked! Please investigate!")
        return None

    key = generate_key(password)

    try:
        user: User = pickle.loads(Fernet(key).decrypt(content))
        return user
    except InvalidToken:
        return None


def get_credentials() -> User:
    """
    Prioritizes: Environment variable > Clean > Encrypted > Input
    """
    # TODO: Get from database

    # First check the environment variables for username *and* password
    if (username := os.getenv(env_var_name_username)) and (password := os.getenv(env_var_name_password)):
        logger.info("Found environment variables: Username and Password.")
        return User(username, password)

    # Now check the clean file
    if os.path.exists(path(clear_password_file)):
        with open(path(clear_password_file)) as f:
            lines = f.read().splitlines()

            if len(lines) not in {0, 2}:
                logger.error(f"Malformed file: {path(clear_password_file)}. Expected 2 lines, found {len(lines)}.")
            elif lines:
                logger.info("Found clean file.")
                return User(*lines)

    assert False, "This is not yet implemented."

    # TODO Implement new username

    # Now check encrypted file
    # if os.path.exists(path(encrypted_password_file)):
    #     logger.info("Found encrypted file.")
    #
    #     if password := os.getenv(env_var_name_encrypted_password):
    #         pass
    #     else:
    #         password = getpass.getpass("Please enter the password for the encrypted file: ")
    #
    #     content = decryptor(password)
    #     if content is None:
    #         logger.error("Supplied the wrong password. Please enter the info manually or restart me!")
    #     else:
    #         logger.info("Password accepted!")
    #         return content
    #
    # # If nothing is found prompt the user
    # logger.info("Please provide authentication for ISIS.")
    # username = input("Username: ")
    #
    # password = getpass.getpass("Password: ")
    #
    # content = User(username, password)
    #
    # encrypt_password = getpass.getpass("Please enter the password to encrypt the file with: ")
    # encryptor(encrypt_password, content)
    #
    # return content
