import base64
import getpass
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from isisdl.backend.utils import User, config, error_text, path, logger
from isisdl.settings import password_hash_algorithm, password_hash_length, password_hash_iterations, env_var_name_username, env_var_name_password, is_autorun, master_password, database_file_location

last_password: Optional[str] = None
last_username: Optional[str] = None


def generate_key(password: str) -> bytes:
    # You might notice that the salt is static. This is a deliberate decision.
    # Since the salt only protects against brute forcing of multiple passwords
    # at once and the password file is limited to a single system
    # (no central storage) it doesn't make sense to include it.
    # It adds useless complexity.
    salt = b"salty~salt"

    kdf = PBKDF2HMAC(algorithm=password_hash_algorithm(), length=password_hash_length, salt=salt, iterations=password_hash_iterations)

    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encryptor(password: str, content: str) -> str:
    global last_password
    last_password = password

    key = generate_key(password)
    return Fernet(key).encrypt(content.encode()).decode()


def decryptor(password: str, content: str) -> Optional[str]:
    key = generate_key(password)

    try:
        decrypted = Fernet(key).decrypt(content.encode()).decode()

        # Only cache the entry if it got successfully decrypted
        global last_password
        last_password = password

        return decrypted

    except InvalidToken:
        return None


def store_user(user: User, password: Optional[str] = None) -> None:
    encrypted = encryptor(password or master_password, user.password)

    config.username = user.username
    config.password = encrypted
    config.password_encrypted = bool(password)


def get_credentials() -> User:
    """
    Prioritizes:
        Cached Password > Environment variable > Database > Input
    """
    global last_username

    # First check the environment variables for username *and* password
    env_username, env_password = os.getenv(env_var_name_username), os.getenv(env_var_name_password)
    if env_username is not None and env_password is not None:
        return User(env_username, env_password)

    # Now try the database
    if config.username is not None and config.password is not None:
        if not config.password_encrypted:
            decrypted = decryptor(master_password, config.password)
            if decrypted is None:
                print(f"""
{error_text} I could not decrypt the password even though it is set to be encrypted with the master password.
This probably means that the master password changed since you saved your password.
Rerun me with `isisdl --init` to re-store your password.
""")
                exit(1)

            return User(config.username, decrypted)

        while True:
            # Maybe use the cache
            if last_password is not None:
                possible_actual_password = decryptor(last_password, config.password)
                if possible_actual_password is not None:
                    return User(config.username, possible_actual_password)

            # Prompt for a password
            user_password = getpass.getpass("Please enter the passphrase: ")
            actual_password = decryptor(user_password, config.password)
            if actual_password is None:
                print("Your password is incorrect. Try again\n")
            else:
                return User(config.username, actual_password)

    if is_autorun:
        exit(1)

    # If nothing is found prompt the user
    print("Please provide authentication for ISIS.")
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    logger.set_username(username)

    return User(username, password)
