"""Package data. In a built wheel, `tree/` holds the org's runtime tree (init.sh, nucleus/, bridges/, ...),
added at build time from git-TRACKED files only (hatch_build.py); `astryx init` copies it into HOME.
In a dev checkout `tree/` is absent and the checkout itself is the tree."""
