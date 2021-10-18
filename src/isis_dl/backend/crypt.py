"""
This repository provides a native python way to store your passwords securely.
This is handled by this file.

# How is this achieved?
For the most part the encryption is handled by the `cryptography.fernet` module.

→ "Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key."

Read the docs:
https://cryptography.io/en/latest/fernet/


1. Encrypting passwords
We assume that the user has provided some sort of string, which resembles a password.
This method of gaining this password is discussed below.

In order to encrypt your athentication you must enable the `-s, --store` argument.
Otherwise nothing will be stored.

    a) Generating a key
        In order to encrypt anything we first need to generate a key. This is done in the `generate_key(…)` function.
        It is a lightweight wrapper for the `PBKDF2HMAC` function from cryptography with all the default settings applied.

        Note: The salt, which is hashed with the password is empty - read the according documentation in the function for more information.

    b) Encrypting
        With a generated key, we can now start encrypting.
        `cryptography.fernet.Fernet` operates on bytes - so we need to encode the object first.

        This is done by involving `pickle`.
        This module can generate bytes which, when executed with `pickle.load(…)`, will instantiate and import all necessary
        dependencies to load the given object.

        e.g. If you pickle an object that uses the `random.randint` function, the `random` module will be imported transparently.


        The function `pickle.dumps(…)` will dump the object into bytes. These are then encrypted with `cryptography.fernet.Fernet.encrypt`.
        The data, which we now obtain, is not decryptable without a password.

        Docs of the function `encrypt(data)`:
    \"""
        Encrypts data passed.
        The result of this encryption is known as a “Fernet token” and has strong privacy and authenticity guarantees.
    \"""

    c) Decrypting
        Decrypting is about as easy as encrypting.

        First, generate another key with a password.
        Then, use the `cryptography.fernet.Fernet.decrypt` function is called.

        Docs of the function `decrypt(token)`:
    \"""
        Decrypts a Fernet token.
        If successfully decrypted you will receive the original plaintext as the result, otherwise an exception will be raised.
        It is safe to use this data immediately as Fernet verifies that the data has not been tampered with prior to returning it.
    \"""


2. Gaining a password from the user.
    This is handled in the function `get_credentials()`.

    See the `src/isis_dl/share/settings.py` file for `clear_password_file` and `encrypted_password_file`.

    First it checks if a file with plaintext passwords is found. If so, it uses that for authentication
    Second it checks if a encrypted file is found. If so, it prompts the user for the password of the encrypted file.
    If none of these checks succeeded, it will prompt you "regularly" for you ISIS-password.


3. Using Clean-Text Passwords
    Sometimes, e.g. in debugging, you don't want to supply your password every time but you also don't want to leave any traces that you *could* forget.
    So, I implemented this.

    This is a newline-split file in the following form:
    ---< Start of file >---
    [\n]*
    < Username >  \n
    < Password > [\n]*
    ---< End of file>---

    This means the accepted language is:
    "\n*(.+)?\n+(.+)?\n*"
    https://regex101.com/r/lSKGIM/1

    If the `clean_password_file` exists and is malformed an error is raised.


Note: I use the same mechanism of en-/ decryption my password manager.
      Thus, I can say with confidence that this will be secure enough for this usecase.
"""

import base64
import logging
import os
import pickle
from getpass import getpass
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import isis_dl.share.settings as settings
from isis_dl.share.utils import User, path, args
import re


# This module handles all stuff that is concerned with authentication.


def generate_key(password):
    # You might notice that the salt is empty. This is a deliberate decision.
    # In this scenario the encrypted file and password file are stored in the same directory.
    # Thus, if a hacker gains access they probably will have access to the salt file as well.

    # As the application is distributed on a local system basis the risc of a data-breach is comparatively low:
    # A hacker might only ever gain access to a single encrypted file.
    salt = b""

    kdf = PBKDF2HMAC(algorithm=settings.hash_algorithm, length=settings.hash_length, salt=salt, iterations=settings.hash_iterations)

    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def store_clear(user: User) -> None:
    with open(path(settings.password_dir, settings.clear_password_file), "w") as f:
        f.write(user.dump())


def encryptor(password: str, obj: object) -> None:
    key = generate_key(password)
    with open(path(settings.password_dir, settings.encrypted_password_file), "wb") as f:
        f.write(Fernet(key).encrypt(pickle.dumps(obj)))


def decryptor(password: str) -> Optional[User]:
    try:
        with open(path(settings.password_dir, settings.encrypted_password_file), "rb") as f:
            content = f.read()

    except FileNotFoundError:
        logging.debug(f"The encrypted file {settings.encrypted_password_file} was not found. It should have been checked! Please investigate!")
        return None

    key = generate_key(password)

    try:
        user: User = pickle.loads(Fernet(key).decrypt(content))
        return user
    except InvalidToken:
        return None


def get_credentials() -> User:
    """
    Prioritizes: Args > Clean > Encrypted > Input
    """
    content = None

    # First check args
    if args.login_info is not None:
        content = User(*args.login_info)

    # Now check the clean file
    elif os.path.exists(path(settings.password_dir, settings.clear_password_file)):
        # Expected to be \n-seperated: `Username\nPassword\n`.
        # May have \n's around it
        with open(path(settings.password_dir, settings.clear_password_file)) as f:
            login_info = re.match("\n*(.+)?\n+(.+)?\n*", f.read()).groups()  # type: ignore

            if len(login_info) != 2:
                logging.error(f"I had a problem reading {settings.clear_password_file}: Malformed file, Expected 2 groups - found {len(login_info)}.")
                raise ValueError

            content = User(*login_info)

    # Now check encrypted file
    elif os.path.exists(path(settings.password_dir, settings.encrypted_password_file)):
        logging.info("Found encrypted file.")
        password = getpass("Please enter the password for the encrypted file: ")

        content = decryptor(password)
        if content is None:
            logging.error("Supplied the wrong password. Please enter the info manually or restart me!")
        else:
            logging.info("Password accepted!")

    # If nothing is found prompt the user
    if content is None:
        logging.info("Please provide authentication for ISIS.")
        username = input("Username: ")
        password = getpass("Password: ")

        content = User(username, password)

    if args.store:
        logging.info("Storing user…")
        if args.clear:
            store_clear(content)  # type: ignore
        else:
            encrypt_password = getpass("Please enter the password to encrypt the file with: ")
            encryptor(encrypt_password, content)

    return content  # type: ignore
