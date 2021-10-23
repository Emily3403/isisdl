# isis_dl

![Tests](https://github.com/Emily3403/isis_dl/actions/workflows/tests.yml/badge.svg)

A downloading utility for the [ISIS](https://isis.tu-berlin.de/) tool of TU-Berlin.

Version 0.2

# Features

- Downloads all Material from all courses of your ISIS page.
- Efficient and dynamic checksum computing for a very good file recognition.
- You can whitelist / blacklist courses with a given course ID.
- Multithreaded: A fixed number of threads can be selected at start time.
- Compatibility: This library will run with any python interpreter that is >= 3.8.

Binary functionality:

- Building of checksums from existing files.
- Automatic unpacking of archives.

## TL;DR

1. Use this library instead of `isia-tub`. It provides a superset of features while having improved performance.
2. Install using `pip install isis_dl`. For a manual installation clone this repository and `pip install .`
3. For a detailed explanation of Command-Line flags please run `isisdl -h`.
4. The first time you run the program you will be prompted if you want to save your password. Look at section encryption
   for more details.

[comment]: <> (TODO: Hyperref)

# Installation

You **will** need a working python3.8 interpreter or above. The script will fail for python3.7 as some new python3.8
features are used.

The recommended installation is via `pip` - a package manager for python. If `pip` is not yet installed with the python
interpreter run

```shell
python3 -m ensurepip
```

to bootstrap pip.

## pip (PyPi)

I have uploaded the repository to the Python Package index ([PyPi](https://pypi.org/)) where one can download it with
the command

```shell
pip install isis_dl
```

Note that you are executing arbitrary code as user. **Do this at your own risk!**

To run the downloader simply type

```shell
isisdl
```

into your favorite shell.

Please note that, if the virtual environment feature is not used, the `~/.local/bin` directory must be in the PATH,
otherwise the executable `isisdl` will not be found.

# Manual

Please note that you have to be in a virtual environment in order for this to work as the installation fails otherwise.

Steps:

- Clone this repository
- `cd isis_dl`
- `pip install -e .`

### Developing

If you want to actively contribute to this repository you will want to install the package in editable mode along with
the development requirements:

```shell
pip install -r requirements_dev.txt
```

This creates a symlink to the source code in the `pip` package location. It will be treated as if it was installed there
directly.

There is no method of installation without `pip` - as the source code expects the module `isis_dl` to be installed as a
package.

# Benchmarks

For a comparison between `isia-tub` and `isis_dl` please see the [Benchmark.md](./Benchmark.md) file.


# Documentation on features

I am planning on moving this part of the documentation to a dedicated doc site.

## File recognition

The file recognition is handled in `src/isis_dl/backend/checksums.py`.

The main idea is to download a small portion of the file and calculate a hash based on that.

As the `requests` library provides a file stream, one can only download the first n Bytes and calculate the hash. The
problem with this idea is that some files have a header, which is permanently changing.

Unfortunately I don't have an idea why this is the case. In order to circumvent this problem the first portion of the
file is skipped based on the file type. The lookup table is located in `src/isis_dl/share/settings.py` - with the
variable being `checksum_num_bytes`.

The format is `<extension>: (<#bytes to ignore>, <#bytes to read>)`.

This means that one can also set the number of bytes to be read for each file type. For files which store a big header (
I'm looking at you `.pdf`) the number of bytes to be read is quite high. For others e.g. `.mp4` it is not.

*Note*: If the file extension is not found the default entry `None` is consulted.

Advantages

- Only download 512 Bytes of every file.
- Can verify independently of directory structure / filenames.
- Lookup is O(1) as a HashSet is used as a datastructure.
- Up to `255 ** 512` unique files can be saved per course using this method.

Disadvantages

- For every file in every course x Bytes have to be downloaded.
- Files are bound to a course.

Note that a default value of `64` suffices to

## Can store your password securely

The entire encryption is handled by the `src/isis_dl/backend/crypt.py`.

The encryption is handled via [Fernet](https://cryptography.io/en/latest/fernet/)
> Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key.
> Fernet is an implementation of symmetric (also known as “secret key”) authenticated cryptography.

The key is generated based on a password you enter and then stored securely.

TODO: This is currently untested. Please enter your password manually for the moment.

### Hash Settings

**Beware:** If you change these settings you will not be able to recover an encrypted file without restoring the
settings. I would not recommend changing them.

You may select any hashing algorithm which is supported. This is any `hashes.HashAlgorithm`. You may also change the
number of iterations, which will increase / decrease the time it takes to encrypt / decrypt respectively.

## A customizable settings file

The file is located at `src/isis_dl/share/settings.py`. For the most part you will want to keep the default settings,
but if they don't fit your needs, you may easily change them.

## Download Directory

The default download directory is `~/isis_dl_downloads`. As the intended installation is via `pip`, there is no good
"current working directory", so one cannot use that.

What can be done, however, is migrating this directory to e.g. the `Desktop/` or `Documents/`.

# Acknowledgements



### isia-tub

Consider checking out the [gitlab](https://git.tu-berlin.de/freddy1404/isia-tub)

This was the original inspiration for this library. At the time isia did not offer the functionality of uri-encoding the
password which lead me to create this library. I have recently implemented this functionality into isia in order to
benchmark and test both solutions.

#### Comparison

Downloading my entire isis directory took 22m8s with isia. This is in contrast to the 11m16s it took with isis_dl

### mCoding

The structure of this project is heavily inspired by the
[GitHub](https://github.com/mCodingLLC/SlapThatLikeButton-TestingStarterProject) of mCoding. Consider giving their
[video](https://www.youtube.com/watch?v=DhUpxWjOhME) about automated testing a shot.

