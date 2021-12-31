from setuptools import setup

# Unfortunately the version cannot be imported. But this does the trick
exec(compile(open('src/isisdl/version.py').read(), 'src/isisdl/version.py', 'exec'))

if __name__ == "__main__":
    setup(version=__version__)  # type: ignore
