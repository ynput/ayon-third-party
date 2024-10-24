import os
import json
import platform
import datetime
import subprocess
import copy

import ayon_api

from ayon_common import (
    validate_file_checksum,
    extract_archive_file,
)
try:
    from ayon_core.lib import get_launcher_storage_dir
except ImportError:
    from ayon_core.lib import get_ayon_appdirs as get_launcher_storage_dir

from .version import __version__
from .constants import ADDON_NAME

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(CURRENT_DIR, "downloads")
NOT_SET = type("NOT_SET", (), {"__bool__": lambda: False})()


class _OIIOArgs:
    download_needed = None
    downloaded_root = NOT_SET
    tools = {
        "oiiotool": NOT_SET,
        "maketx": NOT_SET,
        "iv": NOT_SET,
        "iinfo": NOT_SET,
        "igrep": NOT_SET,
        "idiff": NOT_SET,
        "iconvert": NOT_SET,
    }


class _FFmpegArgs:
    download_needed = None
    downloaded_root = NOT_SET
    tools = {
        "ffmpeg": NOT_SET,
        "ffprobe": NOT_SET,
    }


class _ThirdPartyCache:
    addon_settings = NOT_SET


def get_addon_settings():
    if _ThirdPartyCache.addon_settings is NOT_SET:
        _ThirdPartyCache.addon_settings = ayon_api.get_addon_settings(
            ADDON_NAME, __version__
        )
    return copy.deepcopy(_ThirdPartyCache.addon_settings)


def get_download_dir(create_if_missing=True):
    """Dir path where files are downloaded."""

    if create_if_missing:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
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
        args (list[str]): ffmpeg arguments.

    Returns:
        bool: True if arguments are valid.
    """

    if not args:
        return False
    return _check_args_returncode(args + ["-version"])


def validate_oiio_args(args):
    """Validate oiio arguments.

    Args:
        args (list[str]): oiio arguments.

    Returns:
        bool: True if arguments are valid.
    """

    if not args:
        return False
    return _check_args_returncode(args + ["--help"])


def _get_addon_endpoint():
    return "addons/{}/{}".format(ADDON_NAME, __version__)


def _get_info_path(name):
    return get_launcher_storage_dir(
        "addons", f"{ADDON_NAME}-{name}.json"
    )


def filter_file_info(name):
    filepath = _get_info_path(name)
    try:
        if os.path.exists(filepath):
            with open(filepath, "r") as stream:
                return json.load(stream)
    except Exception:
        print("Failed to load {} info from {}".format(
            name, filepath
        ))
    return []


def store_file_info(name, info):
    filepath = _get_info_path(name)
    root, filename = os.path.split(filepath)
    os.makedirs(root, exist_ok=True)
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

    response = ayon_api.get("{}/files_info".format(
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
    return next(
        (
            file_info
            for file_info in files_info
            if (
                file_info["name"] == name
                and file_info["platform"] == platform_name
            )
        ),
        None
    )


def get_downloaded_ffmpeg_root():
    if _FFmpegArgs.downloaded_root is not NOT_SET:
        return _FFmpegArgs.downloaded_root

    server_ffmpeg_info = _find_file_info("ffmpeg", get_server_files_info())
    root = None
    for existing_info in get_downloaded_ffmpeg_info():
        if existing_info["checksum"] != server_ffmpeg_info["checksum"]:
            continue
        found_root = existing_info["root"]
        if os.path.exists(found_root):
            root = found_root
            break

    _FFmpegArgs.downloaded_root = root
    return _FFmpegArgs.downloaded_root


def get_downloaded_oiio_root():
    if _OIIOArgs.downloaded_root is not NOT_SET:
        return _OIIOArgs.downloaded_root

    server_oiio_info = _find_file_info("oiio", get_server_files_info())
    root = None
    for existing_info in get_downloaded_oiio_info():
        if existing_info["checksum"] != server_oiio_info["checksum"]:
            continue
        found_root = existing_info["root"]
        if os.path.exists(found_root):
            root = found_root
            break
    _OIIOArgs.downloaded_root = root
    return _OIIOArgs.downloaded_root


def _fill_ffmpeg_tool_args(tool_name, addon_settings=None):
    if tool_name not in _FFmpegArgs.tools:
        raise ValueError("Invalid tool name '{}'. Expected {}".format(
            tool_name,
            ", ".join(["'{}'".format(t) for t in _FFmpegArgs.tools])
        ))

    if addon_settings is None:
        addon_settings = get_addon_settings()
    platform_name = platform.system().lower()
    ffmpeg_settings = addon_settings["ffmpeg"]
    if ffmpeg_settings["use_downloaded"]:
        if is_ffmpeg_download_needed(addon_settings):
            download_ffmpeg()

        path_parts = [get_downloaded_ffmpeg_root()]
        if platform_name == "windows":
            path_parts.append("bin")
            tool_name = "{}.exe".format(tool_name)
        path_parts.append(tool_name)

        args = [
            os.path.sep.join(path_parts)
        ]
        if not validate_ffmpeg_args(args):
            args = None
        _FFmpegArgs.tools[tool_name] = args
        return args

    for custom_args in ffmpeg_settings["custom_args"][tool_name]:
        if custom_args and validate_ffmpeg_args(custom_args):
            _FFmpegArgs.tools[tool_name] = custom_args
            return custom_args

    custom_roots = list(
        ffmpeg_settings
        ["custom_roots"]
        [platform_name]
    )
    filtered_roots = []
    format_data = dict(os.environ.items())
    for root in custom_roots:
        if not root:
            continue
        try:
            root = root.format(**format_data)
        except (ValueError, KeyError):
            print("Failed to format root '{}'".format(root))

        if os.path.exists(root):
            filtered_roots.append(root)

    final_args = None
    for root in filtered_roots:
        tool_path = os.path.join(root, tool_name)
        args = [tool_path]
        if validate_ffmpeg_args(args):
            final_args = args
            break
    _FFmpegArgs.tools[tool_name] = final_args
    return final_args


def _fill_oiio_tool_args(tool_name, addon_settings=None):
    if tool_name not in _OIIOArgs.tools:
        raise ValueError("Invalid tool name '{}'. Expected {}".format(
            tool_name,
            ", ".join(["'{}'".format(t) for t in _OIIOArgs.tools])
        ))

    if addon_settings is None:
        addon_settings = get_addon_settings()

    platform_name = platform.system().lower()
    oiio_settings = addon_settings["oiio"]
    if oiio_settings["use_downloaded"]:
        if is_oiio_download_needed(addon_settings):
            download_oiio()

        path_parts = [get_downloaded_oiio_root()]
        if platform_name == "linux":
            path_parts.append("bin")
        elif platform_name == "windows":
            tool_name = "{}.exe".format(tool_name)
        path_parts.append(tool_name)

        args = [
            os.path.sep.join(path_parts)
        ]
        if not validate_oiio_args(args):
            args = None
        _OIIOArgs.tools[tool_name] = args
        return args

    for custom_args in oiio_settings["custom_args"][tool_name]:
        if custom_args and validate_oiio_args(custom_args):
            _OIIOArgs.tools[tool_name] = custom_args
            return custom_args

    custom_roots = list(
        oiio_settings
        ["custom_roots"]
        [platform_name]
    )
    filtered_roots = []
    format_data = dict(os.environ.items())
    for root in custom_roots:
        if not root:
            continue
        try:
            root = root.format(**format_data)
        except (ValueError, KeyError):
            print("Failed to format root '{}'".format(root))

        if os.path.exists(root):
            filtered_roots.append(root)

    final_args = None
    for root in filtered_roots:
        tool_path = os.path.join(root, tool_name)
        args = [tool_path]
        if validate_oiio_args(args):
            final_args = args
            break
    _OIIOArgs.tools[tool_name] = final_args
    return final_args


def is_ffmpeg_download_needed(addon_settings=None):
    """Check if is download needed.

    Returns:
        bool: Should be config downloaded.
    """

    if _FFmpegArgs.download_needed is not None:
        return _FFmpegArgs.download_needed

    if addon_settings is None:
        addon_settings = get_addon_settings()
    ffmpeg_settings = addon_settings["ffmpeg"]
    download_needed = False
    if ffmpeg_settings["use_downloaded"]:
        # Check what is required by server
        ffmpeg_root = get_downloaded_ffmpeg_root()
        download_needed = not bool(ffmpeg_root)

    _FFmpegArgs.download_needed = download_needed
    return _FFmpegArgs.download_needed


def is_oiio_download_needed(addon_settings=None):
    """Check if is download needed.

    Returns:
        bool: Should be config downloaded.
    """

    if _OIIOArgs.download_needed is not None:
        return _OIIOArgs.download_needed

    if addon_settings is None:
        addon_settings = get_addon_settings()
    oiio_settings = addon_settings["oiio"]

    download_needed = False
    if oiio_settings["use_downloaded"]:
        oiio_root = get_downloaded_oiio_root()
        download_needed = not bool(oiio_root)
    _OIIOArgs.download_needed = download_needed
    return _OIIOArgs.download_needed


def _download_file(file_info, dirpath, progress=None):
    filename = file_info["filename"]
    checksum = file_info["checksum"]
    checksum_algorithm = file_info["checksum_algorithm"]

    zip_filepath = ayon_api.download_addon_private_file(
        ADDON_NAME,
        __version__,
        filename,
        dirpath,
        progress=progress
    )

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
            "Couldn't find ffmpeg source file for platform '{}'"
        ).format(platform.system()))

    _download_file(file_info, dirpath, progress=progress)

    ffmpeg_info = get_downloaded_ffmpeg_info()
    existing_item = next(
        (
            item
            for item in ffmpeg_info
            if item["root"] == dirpath
        ),
        None
    )
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

    _FFmpegArgs.download_needed = False
    _FFmpegArgs.downloaded_root = NOT_SET


def download_oiio(progress=None):
    dirpath = os.path.join(get_download_dir(), "oiio")

    files_info = get_server_files_info()
    file_info = _find_file_info("oiio", files_info)
    if file_info is None:
        raise ValueError((
            "Couldn't find OpenImageIO source file for platform '{}'"
        ).format(platform.system()))

    _download_file(file_info, dirpath, progress=progress)

    oiio_info = get_downloaded_oiio_info()
    existing_item = next(
        (
            item
            for item in oiio_info
            if item["root"] == dirpath
        ),
        None
    )

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

    _OIIOArgs.download_needed = False
    _OIIOArgs.downloaded_root = NOT_SET


def get_ffmpeg_arguments(tool_name="ffmpeg"):
    """Get arguments to run one of ffmpeg tools.

    Args:
        tool_name (Optional[Literal[ffmpeg, ffprobe]]): Name of
            tool for which arguments should be returned.

    Returns:
        list[str]: Path to OpenImageIO directory.
    """

    args = _FFmpegArgs.tools.get(tool_name, NOT_SET)
    if args is NOT_SET:
        args = _fill_ffmpeg_tool_args(tool_name)
    return copy.deepcopy(args)


def get_oiio_arguments(tool_name="oiiotool"):
    """Get arguments to run one of OpenImageIO tools.

    Possible OIIO tools:
        oiiotool, maketx, iv, iinfo, igrep, idiff, iconvert

    Args:
        tool_name (Optional[str]): Name of OIIO tool.

    Returns:
        str: Path to zip info file.
    """

    args = _OIIOArgs.tools.get(tool_name, NOT_SET)
    if args is NOT_SET:
        args = _fill_oiio_tool_args(tool_name)
    return copy.deepcopy(args)
