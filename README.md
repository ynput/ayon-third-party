# 3rd Party dependency
Binary dependency executables that are required for pipeline integration by AYON core plugin.

## Intro
AYON core requires ffmpeg and OpenImageIO tools for image processing. Both executables can be added as part of server addon so desktop application will download them on demand, or have settings where can be disabled that option and define different executable arguments that will be used instead. That can be configured per platform.

Files are not part of repository and are downloaded on package creation. We do not expect the package creation to be done often, we hope that it should be done once a year with new releases of dependency binaries.


## How to start
Run `./create_package.py` script which should download required files. Created package should be moved to server addons. Enable the addon on server, and that's it.

### Issues
We do not support binaries for all platforms. We do not supply `oiiotool` for MacOS.
