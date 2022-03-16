# isisdl

![Tests](https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg)

A downloading utility for [ISIS](https://isis.tu-berlin.de/) of TU-Berlin. Download all your files and videos from ISIS.

## Features

### It is *fast*

Once all files are downloaded it takes about 5s to synchronize your files with ISIS.

### Compatibility

This library will run with any python interpreter that is >=  3.8.

Linux, macOS and Windows are supported.

There are also a variety of tests that ensure everything is working properly across all platforms.

### Compression of videos

You can easily save space on your hard drive by executing `isisdl-compress`. `ffmpeg` will be executed and will compress
all the videos into the H265 codec.
Read [here](https://www.boxcast.com/blog/hevc-h.265-vs.-h.264-avc-whats-the-difference) why it is superior to the H264
codec.

The compressed files will be recognized by `isisdl` the same way they would be if they were H264 even though it is an
entirely different file. You could even lose the central database, and they can be recovered.

Read in the [wiki]() for further detail on how it is implemented.

### Automatic running of `isisdl`

Note: This option is currently only supported on linux. 

If you accept the option in the configuration wizard, `isisdl` will be automatically executed every hour. Now every new file
will automagically appear in the `~/isisdl` directory.

## Installation

```shell
pip install isisdl
```

If you are having problems see the [troubleshoot guide](https://github.com/Emily3403/isisdl/wiki/Installation#help-my-install-isnt-working) for solutions.


## Experimental Installation

I am currently in the process of testing [nuitka](https://nuitka.net/) to compile the python code into static
executables. See the GitHub releases page for a binary for your system. It *should* work. If it doesn't feel free to
submit a bug report.

## Executing the program

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
copyright infringement. If you want to participate in that you can soon™ request access.

### Distributing with the AUR

Binary distribution is *really* easy. Do it with the aur and the release-binaries. They will have some different features like hard-
coded no-update and maybe some other stuff
