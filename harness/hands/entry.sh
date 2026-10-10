#!/bin/sh
# The cell's long-lived process: a virtual display for a HEADFUL chromium (S3 will stream it).
# Each driver action arrives as its own `docker exec … node /hands/drive.mjs` from the executor.
exec Xvfb :99 -screen 0 1280x800x24 -nolisten tcp
