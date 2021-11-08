# isis_dl

![Tests](https://github.com/Emily3403/isis_dl/actions/workflows/tests.yml/badge.svg)

A downloading utility for the [ISIS](https://isis.tu-berlin.de/) tool of TU-Berlin.

Version 0.4

## Features

- Downloads all Material from all courses from your ISIS profile.
- Efficient and dynamic checksum computing for a very good file recognition.
- You can whitelist / blacklist courses with a given course ID.
- Multithreaded: A fixed number of threads can be selected at start time.
- Compatibility: This library will run with any python interpreter that is ≥ 3.8.

Binary functionality:

- Building and testing of checksums from existing files.
- Automatic unpacking of archives.

## Installation

You **will** need a working python3.8 interpreter or above. The script will fail for python3.7 as some new python3.8
features are used.

If you are familiar with `pip` and have it set up, simply install it with

```shell
pip install isis_dl
```

To run the executable type
```shell
isisdl
```
into your favorite shell.

For more detailed instructions on installing (including the manual installation) please consult the wiki pages.

[comment]: <> (TODO: Hyperref)

## Acknowledgements

### isia-tub

Consider checking out the [gitlab](https://git.tu-berlin.de/freddy1404/isia-tub)

This was the original inspiration for this library. At the time isia did not offer the functionality of uri-encoding the
password which lead me to create this library. I have recently implemented this functionality into isia in order to
benchmark and test both solutions.

#### Comparison

Downloading my entire isis directory took 22m8s with isia. This is in contrast to the 11m16s it took with isis_dl

### mCoding

The structure of this project is heavily inspired by the
[GitHub](https://github.com/mCodingLLC/SlapThatLikeButton-TestingStarterProject) of mCoding.

