import os
import json
import platform
import datetime
import subprocess

import ayon_api

from ayon_common import (
    get_ayon_appdirs,
    validate_file_checksum,
    extract_archive_file,
)

from .version import __version__
from .constants import ADDON_NAME

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(CURRENT_DIR, "downloads")
NOT_SET = type("NOT_SET", (), {"__bool__": lambda: False})()


class _ThirdPartyCache:
    ffmpeg_download_needed = None
    oiio_download_needed = None

    downloaded_ffmpeg_root = NOT_SET
    downloaded_oiio_root = NOT_SET

    ffmpeg_arguments = NOT_SET
    oiio_arguments = NOT_SET


def get_download_dir(create_if_missing=True):
    """Dir path where files are downloaded."""

    if create_if_missing and not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    return DOWNLOAD_DIR



def _check_args_returncode(args):
    try:
        kwargs = {}
        if platform.system().lower() == "windows":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )

        if hasattr(subprocess, "DEVNULL"):
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **kwargs
            )
            proc.wait()
        else:
            with open(os.devnull, "w") as devnull:
                proc = subprocess.Popen(
                    args, stdout=devnull, stderr=devnull, **kwargs
                )
                proc.wait()

    except Exception:
        return False
    return proc.returncode == 0


def validate_ffmpeg_args(args):
    """Validate ffmpeg arguments.

    Args:
        args (str): ffmpeg arguments.

    Returns:
        bool: True if arguments are valid.
    """

    if not args:
        return False

    return _check_args_returncode(args + ["-version"])


def validate_oiio_args(args):
    """Validate oiio arguments.

    Args:
        args (str): oiio arguments.

    Returns:
        bool: True if arguments are valid.
    """

    if not args:
        return False
    return _check_args_returncode(args + ["--help"])


def _get_addon_endpoint():
    return "addons/{}/{}".format(ADDON_NAME, __version__)


def _get_info_path(name):
    return get_ayon_appdirs(
        "addons", "{}-{}.json".format(ADDON_NAME, name))


def filter_file_info(name):
    filepath = _get_info_path(name)
    try:
        if os.path.exists(filepath):
            with open(filepath, "r") as stream:
                return json.loads(stream)
    except Exception:
        print("Failed to load {} info from {}".format(
            name, filepath
        ))
    return {}


def store_file_info(name, info):
    filepath = _get_info_path(name)
    root, filename = os.path.split(filepath)
    if not os.path.exists(root):
        os.makedirs(root)
    with open(filepath, "w") as stream:
        json.dump(info, stream)


def get_downloaded_ffmpeg_info():
    return filter_file_info("ffmpeg")


def store_downloaded_ffmpeg_info(ffmpeg_info):
    store_file_info("ffmpeg", ffmpeg_info)


def get_downloaded_oiio_info():
    return filter_file_info("oiio")


def store_downloaded_oiio_info(oiio_info):
    store_file_info("oiio", oiio_info)


def get_server_files_info():
    """Receive zip file info from server.

    Information must contain at least 'filename' and 'hash' with md5 zip
    file hash.

    Returns:
        list[dict[str, str]]: Information about files on server.
    """

    response = ayon_api.get("{}/ocio_zip_info".format(
        _get_addon_endpoint()
    ))
    response.raise_for_status()
    return response.data


def _find_file_info(name, files_info):
    """Find file info by name.

    Args:
        name (str): Name of file to find.
        files_info (list[dict[str, str]]): List of file info dicts.

    Returns:
        Union[dict[str, str], None]: File info data.
    """

    platform_name = platform.system().lower()
    for file_info in files_info:
        if (
            file_info["name"] == name
            and file_info["platform"] == platform_name
        ):
            return file_info
    return None


def get_downloaded_ffmpeg_root():
    if _ThirdPartyCache.downloaded_ffmpeg_root is not NOT_SET:
        return _ThirdPartyCache.downloaded_ffmpeg_root

    server_ffmpeg_info = _find_file_info("ffmpeg", get_server_files_info())
    for existing_info in get_downloaded_ffmpeg_info():
        if existing_info["checksum"] == server_ffmpeg_info["checksum"]:
            _ThirdPartyCache.downloaded_ffmpeg_root = existing_info["root"]
            return existing_info["root"]

    _ThirdPartyCache.downloaded_ffmpeg_root = None
    return None


def get_downloaded_oiio_root():
    if _ThirdPartyCache.downloaded_oiio_root is not NOT_SET:
        return _ThirdPartyCache.downloaded_oiio_root

    server_ffmpeg_info = _find_file_info("oiio", get_server_files_info())
    for existing_info in get_downloaded_ffmpeg_info():
        if existing_info["checksum"] == server_ffmpeg_info["checksum"]:
            _ThirdPartyCache.downloaded_oiio_root = existing_info["root"]
            return existing_info["root"]

    _ThirdPartyCache.downloaded_oiio_root = None
    return None


def is_ffmpeg_download_needed():
    """Check if is download needed.

    Returns:
        bool: Should be config downloaded.
    """

    if _ThirdPartyCache.ffmpeg_download_needed is not None:
        return _ThirdPartyCache.ffmpeg_download_needed

    # TODO load settings for custom ffmpeg arguments

    # Check what is required by server
    ffmpeg_root = get_downloaded_ffmpeg_root()
    _ThirdPartyCache.ffmpeg_download_needed = not bool(ffmpeg_root)
    return _ThirdPartyCache.ffmpeg_download_needed


def is_oiio_download_needed():
    """Check if is download needed.

    Returns:
        bool: Should be config downloaded.
    """

    if _ThirdPartyCache.oiio_download_needed is not None:
        return _ThirdPartyCache.oiio_download_needed

    # TODO load settings for custom ffmpeg arguments

    # Check what is required by server
    oiio_root = get_downloaded_oiio_root()
    _ThirdPartyCache.oiio_download_needed = not bool(oiio_root)
    return _ThirdPartyCache.oiio_download_needed


def _download_file(file_info, dirpath, progress=None):
    filename = file_info["filename"]
    checksum = file_info["checksum"]
    checksum_algorithm = file_info["checksum_algorithm"]

    zip_filepath = os.path.join(dirpath, filename)
    endpoint = "{}/private/{}".format(
        _get_addon_endpoint(), filename
    )
    ayon_api.download_file(endpoint, zip_filepath, progress=progress)

    try:
        if not validate_file_checksum(
                zip_filepath, checksum, checksum_algorithm
        ):
            raise ValueError(
                "Downloaded file hash does not match expected hash"
            )
        extract_archive_file(zip_filepath, dirpath)

    finally:
        os.remove(zip_filepath)


def download_ffmpeg(progress=None):
    """Download ffmpeg from server.

    Todos:
        Add safeguard to avoid downloading of the file from multiple
            processes at once.

    Args:
        progress (ayon_api.TransferProgress): Keep track about download.
    """

    dirpath = os.path.join(get_download_dir(), "ffmpeg")

    files_info = get_server_files_info()
    file_info = _find_file_info("ffmpeg", files_info)
    if file_info is None:
        raise ValueError((
            "Couldn't find ffmpeg source file for platoform '{}'"
        ).format(platform.system()))

    _download_file(file_info, dirpath, progress=progress)

    ffmpeg_info = get_downloaded_ffmpeg_info()
    existing_item = None
    for item in ffmpeg_info:
        if item["root"] == dirpath:
            existing_item = item
            break

    if existing_item is None:
        existing_item = {}
        ffmpeg_info.append(existing_item)
    existing_item.update({
        "root": dirpath,
        "checksum": file_info["checksum"],
        "checksum_algorithm": file_info["checksum_algorithm"],
        "downloaded": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    store_downloaded_ffmpeg_info(ffmpeg_info)

    _ThirdPartyCache.ffmpeg_download_needed = False


def download_oiio(progress=None):
    dirpath = os.path.join(get_download_dir(), "oiio")

    files_info = get_server_files_info()
    file_info = _find_file_info("oiio", files_info)
    if file_info is None:
        raise ValueError((
            "Couldn't find ffmpeg source file for platoform '{}'"
        ).format(platform.system()))

    _download_file(file_info, dirpath, progress=progress)

    oiio_info = get_downloaded_oiio_info()
    existing_item = None
    for item in oiio_info:
        if item["root"] == dirpath:
            existing_item = item
            break

    if existing_item is None:
        existing_item = {}
        oiio_info.append(existing_item)
    existing_item.update({
        "root": dirpath,
        "checksum": file_info["checksum"],
        "checksum_algorithm": file_info["checksum_algorithm"],
        "downloaded": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    store_downloaded_oiio_info(oiio_info)

    _ThirdPartyCache.oiio_download_needed = False


def get_custom_ffmpeg_arguments(tool_name, settings):
    # TODO implement
    return []


def get_custom_oiio_arguments(tool_name, settings):
    # TODO implement
    return []


def get_ffmpeg_arguments(tool_name="ffmpeg"):
    """Get arguments to run one of ffmpeg tools.

    Args:
        tool_name (Optional[Literal[ffmpeg, ffprobe]]): Name of
            tool for which arguments should be returned.

    Returns:
        list[str]: Path to OCIO config directory.
    """

    if _ThirdPartyCache.ffmpeg_arguments is not NOT_SET:
        return _ThirdPartyCache.ffmpeg_arguments

    settings = ayon_api.get_addon_settings(ADDON_NAME, __version__)
    args = get_custom_ffmpeg_arguments(tool_name, settings)
    if args:
        return args

    if is_ffmpeg_download_needed():
        download_ffmpeg()
    return [os.path.join(
        get_download_dir(),
        "ffmpeg",
        tool_name
    )]


def get_oiio_arguments(tool_name="oiiotool"):
    """Get arguments to run one of OpenImageIO tools.

    Possible OIIO tools:
        oiiotool, maketx, iv, iinfo, igrep, idiff, iconvert

    Args:
        tool_name (Optional[str]): Name of OIIO tool.

    Returns:
        str: Path to zip info file.
    """

    if _ThirdPartyCache.oiio_arguments is not NOT_SET:
        return _ThirdPartyCache.oiio_arguments

    settings = ayon_api.get_addon_settings(ADDON_NAME, __version__)
    args = get_custom_oiio_arguments(tool_name, settings)
    if args:
        return args

    if is_oiio_download_needed():
        download_oiio()
    return [os.path.join(
        get_download_dir(),
        "oiio",
        tool_name
    )]