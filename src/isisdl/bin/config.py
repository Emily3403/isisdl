#!/usr/bin/env python3
from getpass import getpass
from typing import Union

from isisdl.backend.crypt import encryptor
from isisdl.backend.database_helper import config_helper
from isisdl.share.settings import is_first_time, env_var_name_username, env_var_name_password


def main():
    if is_first_time or True:
        print("""It seams as if this is your first time executing isisdl. Welcome <3

I will guide you through ~2min of configuration.
There are some powerful features in this library that are opt-in.
Please read the prompts carefully.

You can re-configure me with `isisdl-config`.
""")

    print(f"""Authentication:

There are four ways of storing your password. 
  1. Encrypted in the database
       You will have to enter your password every time.
       
  2. Clear text in the database
       No password required, but less security
  
  3. Set username and password via environment variables
       Username = {env_var_name_username} 
       Password = {env_var_name_password}

  4. Manually entering the information every time
       Most secure, but also most annoying
       """)

    config_helper.delete_config()

    while True:
        choice = input("Please choose the way of authentication: ")
        if choice in {"1", "2", "3", "4"}:
            break

        print("\nI did not quite catch that.")

    config_helper.set_how_user_is_stored(int(choice))

    if choice in {"1", "2"}:
        print("Please provide authentication for ISIS.")
        username = input("Username (ISIS): ")
        password: Union[str, bytes] = getpass("Password (ISIS): ")
        if choice == "1":
            enc_password = getpass("Password (Encrypt): ")
            password = encryptor(enc_password, password)

        config_helper.set_user(username, password)

    else:
        print("Alright, no passwords will be stored.")


#    Which mode of file name conversion?
    print(r"""For some applications the file name is important.
Some programming languages have restrictions / inconveniences when working with specific characters.
To combat this you may want to enable a specific file name scheme.

If you already have existing files they will be renamed automatically 
and transparently with the next startup of `isisdl`.

    1. No replacing.
         All characters are left as they are.
    
    2. Replace and filter not unix safe chars 
         "ä" → "ae"
         "ö" → "oe"
         "ü" → "ue"
         "/\t\n\r\v\f" → "_"
    
    3. Replace all non-url safe characters
         "#%&/:;<=>@\^`|~-$" → "."
         "[]{}" → "()"
    """)

    while True:
        choice = input("Please choose the file naming scheme: ")
        if choice in {"1", "2", "3"}:
            break

        print("\nI did not quite catch that.")

    config_helper.set_filename_scheme(int(choice))

    # Throttler





if __name__ == '__main__':
    main()
