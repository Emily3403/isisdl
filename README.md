# isisdl

![Tests](https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg)

A downloading utility for [ISIS](https://isis.tu-berlin.de/) of TU-Berlin. Download all your files and videos from ISIS.

## Features

### It is *fast*

Once all files are downloaded it takes about 5s to synchronize your files with ISIS.

### Compatibility

This library will run with any python interpreter that is ≥ 3.8.

Linux, macOS and Windows are supported. There are also a variety of tests that ensure everything is working properly.

### Multithreaded

A fixed number of download threads may be selected at start time with the command-line-option `-n`.

### Easy black- / whitelisting of courses

When first installing you may select courses that will be white- or blacklisted.

These may also be set with the command-line-options `-b` and `-w`.

## Installation

If you have a working `pip` installment skip the following part (to [here](#pip))

### Python

#### Linux

If you are using Linux you are in luck: Everything should be installed. Check with `pip -V` for an existing
installation.

The output should look something like this

```
pip 21.3.1 from /home/emily/.local/lib/python3.10/site-packages/pip (python 3.10)
```

Also check that `$HOME/.local/bin` is in the `PATH`. Otherwise, the executable won't be found.

#### Windows

First install python from [here](https://www.python.org/downloads/release/python-3101). Then ensure you have pip
installed with [this](https://pip.pypa.io/en/stable/installation/) guide.

### pip

With a working python interpreter and pip installation type the following into your favorite shell

```shell
pip install isisdl
```

Afterwards everything is installed.

### Executing the program

The following executables are shipped:

```
isisdl
isisdl-config
isisdl-sync
isisdl-compress
```

The base executable `isisdl` is responsible for downloading your content.

The executable `isisdl-config` is responsible for reconfiguring your setup.

If your database gets corrupted / deleted you can re-build it by executing `isisdl-sync`. This will ensure all files are
present and unaltered.

To compress videos execute `isisdl-compress`. This will decrease the filesize *massively*. It does cost a lot of CPU so,
it might not be worth for you, especially if you plan to delete the videos anyway.

## Future Ideas

### Sharing of compressed videos

Compressed videos could be saved and distributed from a central server. The access would be restricted, so there is no
copyright infringement. If you want to participate in that you can request access
[here](https://www.youtube.com/watch?v=dQw4w9WgXcQ).