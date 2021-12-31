# isisdl

![Tests](https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg)

A downloading utility for the [ISIS](https://isis.tu-berlin.de/) tool of TU-Berlin.

Version 0.5.1

## Features

- Download all Files and Videos from your subscribed ISIS Courses.
- Recognize already downloaded and updated files.
- Easy black- / whitelisting (matched by substring) of Courses.
- Multithreaded: A fixed number of threads may be selected at start time.
- Compatibility: This library will run with any python interpreter that is ≥ 3.8.
- Automatic unpacking of archives.
- Compressing of videos.

[//]: # (TODO: Hyperref / more wiki pages)

## Installation

You **will** need a working python3.8 interpreter or above.
Simply install this library with `pip` in your favorite environment.
```shell
pip install isisdl
```

To run the executable type `isisdl` into your favorite shell.
Note that the path `~/.local/bin` has to be in the `PATH` in order to execute it.

For more detailed instructions on installing (including the manual installation) please consult the wiki pages [here]().

[//]: # (TODO: Hyperref)


# Feedback

If you have any ideas on which characters best to replace with an other char - e.g. umlaut: 'ä' → 'ae' - feedback 
would be greatly appreciated!