# isis_dl

A downloading utility for the [ISIS](https://isis.tu-berlin.de/) tool of TU-Berlin.

Version 0.1

## Features

### Downloads all Material from all courses of your ISIS page.

- You can whitelist / blacklist courses with a given course ID. [TODO]
- Multithreaded: A fixed number of threads can be selected at start time.
- Compatibility: This library will run with any python interpreter that is >= 3.8.
- Automatic unpacking of archives.
- Efficient and dynamic checksum computing for a very good file recognition.

### File recognition

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

- Only download x Bytes of every file.
- Can verify independently of directory structure / filenames.
- Lookup is O(1) as a HashSet is used as a datastructure.
- Up to `255 ** x` unique files can be saved per course using this method.

Disadvantages

- For every file in every course x Bytes have to be downloaded.
- Files are bound to a course.

### Can store your password securely

The entire encryption is handled by the `src/isis_dl/backend/crypt.py`.

The encryption is handled via [Fernet](https://cryptography.io/en/latest/fernet/)
> Fernet guarantees that a message encrypted using it cannot be manipulated or read without the key.
> Fernet is an implementation of symmetric (also known as “secret key”) authenticated cryptography.

The key is generated based on a password you enter and then stored securely.

TODO: This is currently untested. Please enter your password manually for the moment.

### A customizable settings file

It is located at `src/isis_dl/share/settings.py`. For the most part you will want to keep the default settings, but if
they don't fit with you, you may easily change them.

#### Download Directory

The default download directory is `~/isis_dl_downloads`. As the intended installation is via `pip`, there is no good "
current working directory", so one cannot use that. What can be done, however, is migrating this directory to e.g.
the `Desktop/` or `Documents/`.

#### Hash Settings

**Beware:** If you change these settings you will not be able to recover an encrypted file without restoring the
settings. I would not recommend changing them.

You may select any hashing algorithm which is supported. This is any `hashes.HashAlgorithm`. You may also change the
number of iterations, which will increase / decrease the time it takes to encrypt / decrypt respectively.

# Installation

As stated above you will need a working python3.8 interpreter or above. The script *will* fail for python3.7 as some new
python3.8 features are used.

The recommended installation is via `pip` - a package manager for python. If `pip` is not yet installed with the python
interpreter run

[comment]: <> (TODO: Hyperref)

```shell
python3 -m ensurepip
```

to bootstrap pip.

## pip

Unfortunately this is not possible at the moment. Please refer to the manual installation.

```shell
pip install isis_dl
```

This can be either done in a virtual environment or globally (even with root).

Please note that the `~/.local/bin` directory must be in the PATH, otherwise

# Manual

This method should only be used when developing as it does **not** provide any benefit if you are not developing.

[comment]: <> (TODO: Enum)
Steps:

- Clone this repository
- `cd isis_dl`
- `pip install -e .`

Note: If you don't install this in a virtual environment please don't supply the `-e` flag.


This creates a symlink to the source code in the `pip` package location. It will be treated as if it was installed there
directly.

There is no method of installation without `pip` - as the source code expects the module `isis_dl` to be installed as a
package.

# TODO

[comment]: <> (![Tests]&#40;https://github.com/mCodingLLC/SlapThatLikeButton-TestingStarterProject/actions/workflows/tests.yml/badge.svg&#41;)
