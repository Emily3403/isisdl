import pytest


def pytest_addoption(parser):
    parser.addoption("--login-info", action="store", default=None, nargs=2)


@pytest.fixture
def user(request):
    return request.config.getoption("--login-info")[0]


@pytest.fixture
def password(request):
    return request.config.getoption("--login-info")[1]
