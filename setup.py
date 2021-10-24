from setuptools import setup

if __name__ == "__main__":
    # Read the version
    try:
        with open("VERSION") as f:
            version = f.read().strip()

    except FileNotFoundError:
        version = "0.0.0"

    setup(version=version)
