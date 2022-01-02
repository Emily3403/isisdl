# isisdl

![Tests](https://github.com/Emily3403/isisdl/actions/workflows/tests.yml/badge.svg)

A downloading utility for the [ISIS](https://isis.tu-berlin.de/) tool of TU-Berlin.

Download all Files and Videos from your subscribed ISIS Courses.

## Features

- It is fast: Only #courses web requests (instead of #files)
- Compatibility: This library will run with any python interpreter that is ≥ 3.8. Every operating system is supported.
- Multithreaded: A fixed number of download threads may be selected at start time with `-n`.
- Easy black- / whitelisting (matched by substring) of Courses with `-b` and  `-w` respectively.

[//]: # (TODO: Hyperref / more wiki pages)

## Installation

### Python

#### Linux

If you are using Linux you are in luck: Everything is installed. Test with `pip -V` to check for an existing
installation.

The output should look something like this

```
pip 21.3.1 from /home/emily/.local/lib/python3.9/site-packages/pip (python 3.9)
```

If your installation is at least `python 3.8`, then everything will work perfectly.

Also check that `$HOME/.local/bin` is in the `PATH`. Otherwise the executables won't be found.

#### Windows

If you don't have python installed already go ahead and install it
from [here](https://www.python.org/ftp/python/3.9.9/python-3.9.9-amd64.exe). In the installation there is an option to
select `pip`. Next time I'm on Windows I will test that.

### Pip

With a working python interpreter and pip installation type the following into your favorite shell

```shell
pip install isisdl
```

### Executing the program

As you might have guessed the base executable is named `isisdl`. The following executables are shipped:

```
- isisdl
- isisdl.
- isisdl-server
- isisdl-clean
- isisdl-update
- isisdl-config
```

I find that executables are the best way to ship all the functionality. If you wish, you may disable these executables
when initializing and when executing `isisdl-config`.

For more information about the executables, their use-cases and other installation methods (from Github) please consult the wiki pages [here]().

[//]: # (TODO: Hyperref)

## Future Ideas

The release of 0.5.1 marks the finalization of the backend and client. With 0.5.2 I plan to release a server version
which can be hosted as a local server. I also plan on releasing a real server which handles stuff but honestly it's not
needed. The client is sooo fast that it really isn't a big effort.

## P2P File sharing

A really cool idea is a peer to peer file transcoding (h264 to h265) circle. We share the work and have the videos in a
better format. I like the h265 codec and would like to transcode all the videos. It saves data in the progress and is
just better all around.

Everyone can download everything from a central server that has 1GiB/s up / down but only 15GB storage space.

### Copyright infringement

Unfortunately most of the content that professors produce is copyrighted material. To circumvent a potential lawsuit the
material is only shared with trusted individuals that all have access to ISIS.

### GPG

One way of enforcing this is with GPG keys. Everyone uploads their GPG key to a keyserver which is known and trusted.
Then we exchange our gpg keys 👉👈 🥺 and afterwards authenticity is guaranteed.

## GPL3

I really like the idea of the GPL3 Licence. Let's see when I can make the switch. And if I have released it under MIT in
a previous version and switch to GPL are then also the previous changed?

I don't plan much more for this library. In particular the backend is basically final and not much will be going on
there. So the only thing I plan to change is the UI.

If there is any feedback you are willing to share run `isisdl-feedback` to submit it to the central server.

### Compression of videos

The compressing of videos is something I would love in the future. These are saved and distributed from a central
server. The access is restricted, so we don't have any copyright infringement. If you want to participate in that you
can request access [here](https://www.youtube.com/watch?v=dQw4w9WgXcQ).

### Authentication

# Feedback

If you have any ideas on which characters best to replace with an other char - e.g. umlaut: 'ä' → 'ae' - feedback would
be greatly appreciated!