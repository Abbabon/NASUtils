# NASUtils

A collection of utilities for my personal NAS, uploaded here for automation, future references, and potential blog posts.

## filesOrganizer

This image includes a python cron script that on activation will look for files under the volume `/input_directory` and divide them into subfolders structures `YYYY/MM` in the volume `/output_parent_directory`.

### Dev Commands

#### Build Image

```sh
 docker build -t file-organizer .
```

#### Start headless (locally)

```sh
 docker run -d --name file-organizer-container -v /path/to/input:/input_directory -v /path/to/output:/output_parent_directory file-organizer
```

## TODO

* [ ] filesOrganizer - Add progress logs of some kind (every 10 files?)