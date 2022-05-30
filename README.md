# isisdl

![Tests](https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg)

A downloading utility for [ISIS](https://isis.tu-berlin.de/) of TU-Berlin. Download all your files and videos from ISIS.

## Features

### It is *fast*

Once all files are downloaded it takes about 5s to synchronize your files with ISIS.

### It downloads *everything*

All the files from all of your ISIS courses are found and downloaded. Also, if a link to a file is posted on the ISIS
page, it will get downloaded. This might work depending on the link. Links to Google Drive and TUBCloud supported, and
there is planned support for youtube, prezi, doi and some more libraries.

*Note*: If you have a specific url you would like to have downloaded, feel free to submit an issue.

### Compatibility

`isisdl` will run on any python interpreter that is ≥ 3.8.

If you do not have access to Python, there is also a standalone executable, which will run on any Linux distribution and
Windows version (with their respective binaries).

There are also a variety of tests that ensure everything is working properly across all platforms.

### Compression of videos

`isisdl` also includes a very convenient frontend for `ffmpeg`.

If you execute `isisdl --compress`, `ffmpeg` will be
executed and compresses all of your downloaded videos into the H265 codec.
Read [here](https://www.boxcast.com/blog/hevc-h.265-vs.-h.264-avc-whats-the-difference) why it is superior to the H264
codec.

The compressed files will be transparently recognized by `isisdl`. This means that you could lose the central
database and be able to recover the files.

Read in the [wiki](https://github.com/Emily3403/isisdl/wiki/Compression) for further details on how it is implemented.

### Support for prioritizing downloads

Once you open any file in the `~/isisdl` directory, this download will be prioritized, if it isn't downloaded already.
This is especially useful, if you either don't want to download all video files, but still be able to view them
with `vlc` (see the `--stream` option), or if you want to start watching videos while the download is still running.

## Installation

### Linux

```shell
pip install isisdl
```

If you are running an Arch based distro, the standalone executable of `isisdl` is also available in the AUR:

```shell
yay -S isisdl
```

### Windows

The recommended installation is by downloading the latest standalone executable from
[here](https://github.com/Emily3403/isisdl/releases/latest/download/isisdl-windows.exe).

There may be a Windows defender / smartscreen warning about this executable not being recognized. This is due to the fact
that there are few Windows users. Simply ignore the warning. 

### Troubleshooting

If you are having problems see the
[troubleshoot guide](https://github.com/Emily3403/isisdl/wiki/Installation#help-my-install-isnt-working) for solutions.

## Additional options

`isisdl` ships with a few different modes of operating:

- `--help`: Displays a helpful message.
- `--init`: Will guide you through the base configuration.
- `--config`: Will gide you through additional configuration.
- `--sync`: Will synchronize the local database with ISIS.
- `--compress`: Launches `ffmpeg` and compresses videos.
- `--stream`: Launches `isisdl` in streaming mode.

[//]: # (- `--subscribe`: Subscribes you to *all* publicly available courses)

[//]: # (- `--unsubscribe`: Unsubscribes you from the courses you subscribed to.)

## Future Ideas

### Sharing of compressed videos

Compressed videos could be saved and distributed from a central server. The access would be restricted, so there is no
copyright infringement. If you want to participate in that you can soon™ request access.

