# import pytest

# For this file we assume the login information is
# Username = "c2Qj43oiavTczwQM"
# Password = "NGCr29xWemJqGpW4"
import os

from isis_dl.share.settings import env_var_name_username


def test_get_credentials_default(user, password):
    assert os.getenv(env_var_name_username) == "ABC"
    pass
