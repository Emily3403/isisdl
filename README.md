# isisdl

![Tests](https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg)

A downloading utility for the [ISIS](https://isis.tu-berlin.de/) tool of TU-Berlin.

Download all your Files and Videos from ISIS.

## Features

### It is fast

Once the database is established and downloaded it takes ~5s to synchronize your files with ISIS.

### Compatibility

This library will run with any python interpreter that is ≥ 3.8.

Every operating system is supported.

### Multithreaded

A fixed number of download threads may be selected at start time with `-n`.

### Easy black- / whitelisting

The course name is matched by substring with a `-b` for blacklist and `-w` for whitelist.

The whitelist takes precedence over the blacklist.

## Installation

If you have a working `pip` installment skip the following part (to [here](#Pip))

### Python

#### Linux

If you are using Linux you are in luck: Everything should be installed. Test with `pip -V` to check for an existing
installation.

The output should look something like this

```
pip 21.3.1 from /home/emily/.local/lib/python3.10/site-packages/pip (python 3.10)
```

Now check that `$HOME/.local/bin` is in the `PATH`. Otherwise, the executables won't be found.

#### Windows

If you don't have python installed already go ahead and install it
from [here](https://www.python.org/downloads/release/python-3101). 

The next time I am on Windows I will complete this part of the documentation.

### Pip

With a working python interpreter and pip installation type the following into your favorite shell

```shell
pip install isisdl
```

Afterwards everything is installed.

### Executing the program

The following executables are shipped:

```
- isisdl
- isisdl-config
- isisdl-sync
```

The base executable `isisdl` is responsible for downloading your content.

The executable `isisdl-config` is responsible for reconfiguring your setup.

The executable `isisdl-sync` is responsible for synchronizing your files with the database and detecting missing /
corrupted files.

## Future Ideas

### Compression of videos

The compressing of videos is something I would love in the future. These are saved and distributed from a central
server. The access is restricted, so we don't have any copyright infringement. If you want to participate in that you
can request access [here](https://www.youtube.com/watch?v=dQw4w9WgXcQ).