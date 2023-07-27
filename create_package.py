"""Prepares server package from addon repo to upload to server.

Requires Python 3.9. (Or at least 3.8+).

This script should be called from cloned addon repo.

It will produce 'package' subdirectory which could be pasted into server
addon directory directly (eg. into `ayon-backend/addons`).

Format of package folder:
ADDON_REPO/package/{addon name}/{addon version}

You can specify `--output_dir` in arguments to change output directory where
package will be created. Existing package directory will always be purged if
already present! This could be used to create package directly in server folder
if available.

Package contains server side files directly,
client side code zipped in `private` subfolder.
"""

import os
import sys
import re
import json
import shutil
import argparse
import platform
import logging
import collections
import zipfile
import hashlib
import urllib.request
from pathlib import Path

from typing import Optional


ADDON_NAME = "ayon_third_party"
ADDON_CLIENT_DIR = "ayon_third_party"

DISTRIBUTE_SOURCE_URL = "https://distribute.openpype.io/thirdparty"
FFMPEG_SOURCES = {
    "windows": {
        "url": f"{DISTRIBUTE_SOURCE_URL}/ffmpeg-4.4-windows.zip",
        "checksum": "dd51ba29d64ee238e7c4c3c7301b19754c3f0ee2e2a729c20a0e2789e72db925",
        "checksum_algorithm": "sha256",
    },
    "linux": {
        "url": f"{DISTRIBUTE_SOURCE_URL}/ffmpeg-4.4-linux.tgz",
        "checksum": "10b9beda57cfbb69b9ed0ce896c0c8d99227b26ca8b9f611040c4752e365cbe9",
        "checksum_algorithm": "sha256",
    },
    "darwin": {
        "url": f"{DISTRIBUTE_SOURCE_URL}/ffmpeg-4.4-macos.tgz",
        "checksum": "95f43568338c275f80dc0cab1e1836a2e2270f856f0e7b204440d881dd74fbdb",
        "checksum_algorithm": "sha256",
    }
}
OIIO_SOURCES = {
    "windows": {
        "url": f"{DISTRIBUTE_SOURCE_URL}/oiio_tools-2.3.10-windows.zip",
        "checksum": "b9950f5d2fa3720b52b8be55bacf5f56d33f9e029d38ee86534995f3d8d253d2",
        "checksum_algorithm": "sha256",
    },
    "linux": {
        "url": f"{DISTRIBUTE_SOURCE_URL}/oiio_tools-2.2.20-linux-centos7.tgz",
        "checksum": "3894dec7e4e521463891a869586850e8605f5fd604858b674c87323bf33e273d",
        "checksum_algorithm": "sha256",
    }
}

# Patterns of directories to be skipped for server part of addon
IGNORE_DIR_PATTERNS = [
    re.compile(pattern)
    for pattern in {
        # Skip directories starting with '.'
        r"^\.",
        # Skip any pycache folders
        "^__pycache__$"
    }
]

# Patterns of files to be skipped for server part of addon
IGNORE_FILE_PATTERNS = [
    re.compile(pattern)
    for pattern in {
        # Skip files starting with '.'
        # NOTE this could be an issue in some cases
        r"^\.",
        # Skip '.pyc' files
        r"\.pyc$"
    }
]


class ZipFileLongPaths(zipfile.ZipFile):
    """Allows longer paths in zip files.

    Regular DOS paths are limited to MAX_PATH (260) characters, including
    the string's terminating NUL character.
    That limit can be exceeded by using an extended-length path that
    starts with the '\\?\' prefix.
    """
    _is_windows = platform.system().lower() == "windows"

    def _extract_member(self, member, tpath, pwd):
        if self._is_windows:
            tpath = os.path.abspath(tpath)
            if tpath.startswith("\\\\"):
                tpath = "\\\\?\\UNC\\" + tpath[2:]
            else:
                tpath = "\\\\?\\" + tpath

        return super(ZipFileLongPaths, self)._extract_member(
            member, tpath, pwd
        )


def safe_copy_file(src_path, dst_path):
    """Copy file and make sure destination directory exists.

    Ignore if destination already contains directories from source.

    Args:
        src_path (str): File path that will be copied.
        dst_path (str): Path to destination file.
    """

    if src_path == dst_path:
        return

    dst_dir = os.path.dirname(dst_path)
    try:
        os.makedirs(dst_dir)
    except Exception:
        pass

    shutil.copy2(src_path, dst_path)


def _value_match_regexes(value, regexes):
    for regex in regexes:
        if regex.search(value):
            return True
    return False


def find_files_in_subdir(
    src_path,
    ignore_file_patterns=None,
    ignore_dir_patterns=None
):
    if ignore_file_patterns is None:
        ignore_file_patterns = IGNORE_FILE_PATTERNS

    if ignore_dir_patterns is None:
        ignore_dir_patterns = IGNORE_DIR_PATTERNS
    output = []

    hierarchy_queue = collections.deque()
    hierarchy_queue.append((src_path, []))
    while hierarchy_queue:
        item = hierarchy_queue.popleft()
        dirpath, parents = item
        for name in os.listdir(dirpath):
            path = os.path.join(dirpath, name)
            if os.path.isfile(path):
                if not _value_match_regexes(name, ignore_file_patterns):
                    items = list(parents)
                    items.append(name)
                    output.append((path, os.path.sep.join(items)))
                continue

            if not _value_match_regexes(name, ignore_dir_patterns):
                items = list(parents)
                items.append(name)
                hierarchy_queue.append((path, items))

    return output


def copy_server_content(addon_output_dir, current_dir, log):
    """Copies server side folders to 'addon_package_dir'

    Args:
        addon_output_dir (str): package dir in addon repo dir
        current_dir (str): addon repo dir
        log (logging.Logger)
    """

    log.info("Copying server content")

    filepaths_to_copy = []
    server_dirpath = os.path.join(current_dir, "server")

    # Version
    src_version_path = os.path.join(current_dir, "version.py")
    dst_version_path = os.path.join(addon_output_dir, "version.py")
    filepaths_to_copy.append((src_version_path, dst_version_path))

    for item in find_files_in_subdir(server_dirpath):
        src_path, dst_subpath = item
        dst_path = os.path.join(addon_output_dir, dst_subpath)
        filepaths_to_copy.append((src_path, dst_path))

    # Copy files
    for src_path, dst_path in filepaths_to_copy:
        safe_copy_file(src_path, dst_path)


def zip_client_side(addon_package_dir, current_dir, log):
    """Copy and zip `client` content into 'addon_package_dir'.

    Args:
        addon_package_dir (str): Output package directory path.
        current_dir (str): Directory path of addon source.
        log (logging.Logger): Logger object.
    """

    client_dir = os.path.join(current_dir, "client")
    if not os.path.isdir(client_dir):
        log.info("Client directory was not found. Skipping")
        return

    log.info("Preparing client code zip")
    private_dir = os.path.join(addon_package_dir, "private")

    if not os.path.exists(private_dir):
        os.makedirs(private_dir)

    src_version_path = os.path.join(current_dir, "version.py")
    dst_version_path = os.path.join(ADDON_CLIENT_DIR, "version.py")

    zip_filepath = os.path.join(os.path.join(private_dir, "client.zip"))
    with ZipFileLongPaths(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add client code content to zip
        for path, sub_path in find_files_in_subdir(client_dir):
            zipf.write(path, sub_path)

        # Add 'version.py' to client code
        zipf.write(src_version_path, dst_version_path)


def download_ffmpeg_zip(private_dir, log):
    zip_files_info = []
    for platform_name, platform_info in FFMPEG_SOURCES.items():
        src_url = platform_info["url"]
        filename = src_url.split("/")[-1]
        ocio_zip_path = private_dir / filename
        log.debug(f"FFmpeg zip from {src_url} -> {ocio_zip_path}")

        log.info("FFmpeg zip download - started")
        urllib.request.urlretrieve(src_url, ocio_zip_path)
        log.info("FFmpeg zip download - finished")

        with open(ocio_zip_path, "rb") as stream:
            filehash = hashlib.sha256(stream.read()).hexdigest()

        zip_files_info.append({
            "name": "ffmpeg",
            "filename": filename,
            "checksum": filehash,
            "checksum_algorithm": "sha256",
            "platform": platform_name,
        })

    return zip_files_info


def download_oiio_zip(private_dir, log):
    zip_files_info = []
    for platform_name, platform_info in OIIO_SOURCES.items():
        src_url = platform_info["url"]
        filename = src_url.split("/")[-1]
        ocio_zip_path = private_dir / filename
        log.debug(f"OIIO zip from {src_url} -> {ocio_zip_path}")

        log.info("OIIO zip download - started")
        urllib.request.urlretrieve(src_url, ocio_zip_path)
        log.info("OIIO zip download - finished")

        with open(ocio_zip_path, "rb") as stream:
            filehash = hashlib.sha256(stream.read()).hexdigest()

        zip_files_info.append({
            "name": "oiio",
            "filename": filename,
            "checksum": filehash,
            "checksum_algorithm": "sha256",
            "platform": platform_name
        })
    return zip_files_info


def create_server_package(
    output_dir: str,
    addon_output_dir: str,
    addon_version: str,
    log: logging.Logger
):
    """Create server package zip file.

    The zip file can be installed to a server using UI or rest api endpoints.

    Args:
        output_dir (str): Directory path to output zip file.
        addon_output_dir (str): Directory path to addon output directory.
        addon_version (str): Version of addon.
        log (logging.Logger): Logger object.
    """

    log.info("Creating server package")
    output_path = os.path.join(
        output_dir, f"{ADDON_NAME}-{addon_version}.zip"
    )
    manifest_data: dict[str, str] = {
        "addon_name": ADDON_NAME,
        "addon_version": addon_version
    }
    with ZipFileLongPaths(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Write a manifest to zip
        zipf.writestr("manifest.json", json.dumps(manifest_data, indent=4))

        # Move addon content to zip into 'addon' directory
        addon_output_dir_offset = len(addon_output_dir) + 1
        for root, _, filenames in os.walk(addon_output_dir):
            if not filenames:
                continue

            dst_root = "addon"
            if root != addon_output_dir:
                dst_root = os.path.join(
                    dst_root, root[addon_output_dir_offset:]
                )
            for filename in filenames:
                src_path = os.path.join(root, filename)
                dst_path = os.path.join(dst_root, filename)
                zipf.write(src_path, dst_path)

    log.info(f"Output package can be found: {output_path}")


def main(
    output_dir: Optional[str]=None,
    skip_zip: bool=False,
    keep_sources: bool=False
):
    log = logging.getLogger("create_package")
    log.info("Start creating package")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    if not output_dir:
        output_dir = os.path.join(current_dir, "package")

    version_filepath = os.path.join(current_dir, "version.py")
    version_content = {}
    with open(version_filepath, "r") as stream:
        exec(stream.read(), version_content)
    addon_version = version_content["__version__"]

    new_created_version_dir = os.path.join(
        output_dir, ADDON_NAME, addon_version
    )
    if os.path.isdir(new_created_version_dir):
        log.info(f"Purging {new_created_version_dir}")
        shutil.rmtree(output_dir)

    log.info(f"Preparing package for {ADDON_NAME}-{addon_version}")

    addon_output_root = os.path.join(output_dir, ADDON_NAME)
    addon_output_dir = os.path.join(addon_output_root, addon_version)
    if not os.path.exists(addon_output_dir):
        os.makedirs(addon_output_dir)

    copy_server_content(addon_output_dir, current_dir, log)

    private_dir = Path(addon_output_dir) / "private"
    if not private_dir.exists():
        private_dir.mkdir(parents=True)

    ffmpeg_files_info = download_ffmpeg_zip(private_dir, log)
    oiio_files_info = download_oiio_zip(private_dir, log)

    ocio_zip_info_path = private_dir / "files_info.json"
    with open(ocio_zip_info_path, "w") as stream:
        json.dump(ffmpeg_files_info + oiio_files_info, stream)

    zip_client_side(addon_output_dir, current_dir, log)

    # Skip server zipping
    if not skip_zip:
        create_server_package(
            output_dir, addon_output_dir, addon_version, log
        )
        # Remove sources only if zip file is created
        if not keep_sources:
            log.info("Removing source files for server package")
            shutil.rmtree(addon_output_root)
    log.info("Package creation finished")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-zip",
        dest="skip_zip",
        action="store_true",
        help=(
            "Skip zipping server package and create only"
            " server folder structure."
        )
    )
    parser.add_argument(
        "--keep-sources",
        dest="keep_sources",
        action="store_true",
        help=(
            "Keep folder structure when server package is created."
        )
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_dir",
        default=None,
        help=(
            "Directory path where package will be created"
            " (Will be purged if already exists!)"
        )
    )

    args = parser.parse_args(sys.argv[1:])
    main(args.output_dir, args.skip_zip, args.keep_sources)
