# Changes

### Bundled all functionality into one executable

Previously there were different executable for major ~ differences. I find that doing it this way is definately worth
doing, but since a static build of `isisdl` conflicts with this, this is deprecated.

### Added external links

Now the entire course is searched for anything that matches an url (regex based). If one is found, it gets queried and
if the `Content-Type` is `application/*`, the page is downloaded.

This means that any url mentioned in ISIS, will now appear as part of the course. Since a web-request has to be sent for
every external url, it takes quite a lot of time. The downloaded information is of course cached, so it does not have to
be retrieved every time.

### More configuration options

Now added the following options:

- Renaming courses
- Following external links
- Should subdirectories be created in the main course directory?

### If you open a not downloaded file, it will get downloaded with priority

This is made possible by the Linux Kernel API inotify. Whenever any program opens any file in the `~/isisdl` directory,
the streaming thread will get notified. It pauses all other downloads and downloads the opened file with maximum
bandwidth.

his is especially useful, if you either don't want to download all video files, but still be able to view them
with `vlc`, or if you want to start watching videos while the download is still running.

Specifically for the former use case I added an option `--stream`, which will launch only the streaming
thread.

### Subscribe to *all* courses

In order for me to limit test `isisdl`, I want to have access to as many courses as possible. Because of that I decided
to implement a way of subscribing to all publicly available courses.

It is done by trying to subscribe to every course with the API. If it was successful, the result is stored in the
database. With this it is also possible to unsubscribe from all courses automatically. Unfortunately this is quite slow
since unsubscribing via the Moodle API is not supported… ([yet]())

## Minor changes

Better progress bar. Split phases in two so the status is actually accurate.

Changed the master password to a sha digest of a string. It now has 64 characters.

Before launching it is checked if you have an active internet connection. If not, `isisdl` is exited gracefully.

`isisdl` will now only ever prompt you 1x for your password.

Fixed a bug where, if you throttle too high (2MiB/s), nothing would get downloaded.

A few bug fixes here and there. Probably also introduced some more :D
