from __future__ import annotations

import os
import json
import platform
import datetime
import shutil
import subprocess
import copy
import hashlib
import zipfile
import tarfile
import typing
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import ayon_api
from ayon_api import TransferProgress

from ayon_core.lib import Logger, CacheItem, get_addons_resources_dir

from .version import __version__
from .constants import ADDON_NAME

if typing.TYPE_CHECKING:
    from .typing import (
        OIIOToolName,
        FFmpegToolname,
        ToolDownloadInfo,
    )

PLATFORM_NAME = platform.system().lower()
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
NOT_SET = type("NOT_SET", (), {"__bool__": lambda: False})()
IMPLEMENTED_ARCHIVE_FORMATS = {
    ".zip", ".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"
}
# Filename where is stored progress of extraction
DIST_PROGRESS_FILENAME = "dist_progress.json"
# How long to wait for other process to download/extract content
DOWNLOAD_WAIT_TRESHOLD_TIME = 20
EXTRACT_WAIT_TRESHOLD_TIME = 20

WINGET_FFMPEG_PACKAGE = "BtbN.FFmpeg.LGPL.7.1"

log = Logger.get_logger(__name__)


class InstallTracker:
    """Track installation progress of FFmpeg or OpenImageIO.

    The tracking abilities are limited to support minimum options for UI.

    Args:
        title (str): Title of tool to install.

    """
    def __init__(self, title: str) -> None:
        self._transfer_progress: TransferProgress | None = None
        self._title: str = title
        self._started: bool = False
        self._finished: bool = False
        self._success: bool = False

    def get_title(self) -> str:
        return self._title

    def get_started(self) -> bool:
        """Installation started.

        Returns:
            bool: True if installation process started, False otherwise.

        """
        return self._started

    def get_finished(self) -> bool:
        """Installation finished.

        Install process finished, but not necessarily successful.

        Returns:
            bool: True if installation process finished, False otherwise.

        """
        return self._finished

    def get_success(self) -> bool:
        """Get installation success status.

        By default, is returned value 'False'. First check for 'get_finished'.

        Returns:
            bool: True if installation was successful, False otherwise.

        """
        return self._success

    def get_progress(self) -> int:
        """Get installation progress.

        Progress is state based and can change during installation.

        Returns:
            int: 0-100 progress of installation. -1 if progress cannot be
                tracked using percentage.

        """
        if self._transfer_progress is None:
            return -1
        if self._transfer_progress.transfer_done:
            return -1
        if self._transfer_progress.transfer_progress is None:
            return -1
        return int(self._transfer_progress.transfer_progress)

    def get_label(self) -> str:
        """Progress label.

        UI label representing current state of installation.

        Returns:
            str: Label of current state of installation.

        """
        if not self._started:
            return "Starting..."

        if self._finished:
            if self._success:
                return "Installed"
            return "Failed!"

        if self._transfer_progress is None:
            return "Installing..."

        if self._transfer_progress.transfer_done:
            return "Extracting..."
        return "Downloading..."

    def set_started(self) -> None:
        """Mark trackers as started."""
        self._started = True

    def set_transfer_progress(
        self, transfer_progress: TransferProgress | None = None
    ) -> None:
        """Set transfer progress."""
        self._transfer_progress = transfer_progress

    def set_finished(self, success: bool = True) -> None:
        """Mark trackers as finished.

        Args:
            success (bool): Whether installation was successful.

        """
        self._finished = True
        self._success = success


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
    addon_settings = CacheItem(lifetime=60)
    server_files_info = None


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

        return super()._extract_member(member, tpath, pwd)


def calculate_file_checksum(
    filepath: str,
    checksum_algorithm: str,
    chunk_size: int = 10000,
) -> str:
    """Calculate file checksum for given algorithm.

    Args:
        filepath (str): Path to a file.
        checksum_algorithm (str): Algorithm to use. ('md5', 'sha1', 'sha256')
        chunk_size (int): Chunk size to read file.
            Defaults to 10000.

    Returns:
        str: Calculated checksum.

    Raises:
        ValueError: File not found or unknown checksum algorithm.

    """
    if not filepath:
        raise ValueError("Filepath is empty.")

    if not os.path.exists(filepath):
        raise ValueError(f"{filepath} doesn't exist.")

    if not os.path.isfile(filepath):
        raise ValueError(f"{filepath} is not a file.")

    func = getattr(hashlib, checksum_algorithm, None)
    if func is None:
        raise ValueError(
            f"Unknown checksum algorithm '{checksum_algorithm}'"
        )

    hash_obj = func()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def validate_file_checksum(
    filepath: str,
    checksum: str,
    checksum_algorithm: str,
) -> bool:
    """Validate file checksum.

    Args:
        filepath (str): Path to file.
        checksum (str): Hash of file.
        checksum_algorithm (str): Type of checksum.

    Returns:
        bool: Hash is valid/invalid.

    Raises:
        ValueError: File not found or unknown checksum algorithm.

    """
    return checksum == calculate_file_checksum(filepath, checksum_algorithm)


def get_archive_ext_and_type(
    archive_file: str
) -> tuple[str | None, str | None]:
    """Get archive extension and type.

    Args:
        archive_file (str): Path to archive file.

    Returns:
        tuple[str | None, str | None]: Archive extension and type.

    """
    tmp_name = archive_file.lower()
    if tmp_name.endswith(".zip"):
        return ".zip", "zip"

    for ext in (
        ".tar",
        ".tgz",
        ".tar.gz",
        ".tar.xz",
        ".tar.bz2",
    ):
        if tmp_name.endswith(ext):
            return ext, "tar"

    return None, None


def extract_archive_file(
    archive_file: str,
    dst_folder: str | None = None,
) -> None:
    """Extract archived file to a directory.

    Args:
        archive_file (str): Path to a archive file.
        dst_folder (str | None): Directory where content will be extracted.
            By default, same folder where archive file is.

    """
    if not dst_folder:
        dst_folder = os.path.dirname(archive_file)

    archive_ext, archive_type = get_archive_ext_and_type(archive_file)

    print("Extracting {} -> {}".format(archive_file, dst_folder))
    if archive_type is None:
        _, ext = os.path.splitext(archive_file)
        raise ValueError((
            f"Invalid file extension \"{ext}\"."
            f" Expected {', '.join(IMPLEMENTED_ARCHIVE_FORMATS)}"
        ))

    if archive_type == "zip":
        zip_file = ZipFileLongPaths(archive_file)
        zip_file.extractall(dst_folder)
        zip_file.close()

    elif archive_type == "tar":
        if archive_ext == ".tar":
            tar_type = "r:"
        elif archive_ext.endswith(".xz"):
            tar_type = "r:xz"
        elif archive_ext.endswith(".gz"):
            tar_type = "r:gz"
        elif archive_ext.endswith(".bz2"):
            tar_type = "r:bz2"
        else:
            tar_type = "r:*"

        try:
            tar_file = tarfile.open(archive_file, tar_type)
        except tarfile.ReadError:
            raise ValueError("corrupted archive")

        tar_file.extractall(dst_folder)
        tar_file.close()


def get_addon_settings() -> dict[str, Any]:
    if not _ThirdPartyCache.addon_settings.is_valid:
        _ThirdPartyCache.addon_settings.update_data(
            ayon_api.get_addon_settings(
                ADDON_NAME, __version__
            )
        )
    return copy.deepcopy(_ThirdPartyCache.addon_settings.get_data())


def _get_addon_endpoint() -> str:
    return f"addons/{ADDON_NAME}/{__version__}"


def get_server_files_info() -> list[ToolDownloadInfo]:
    """Receive zip file info from server.

    Information must contain at least 'filename' and 'hash' with md5 zip
    file hash.

    Returns:
        list[dict[str, str]]: Information about files on server.

    """
    # Cache server files info, they won't change
    if _ThirdPartyCache.server_files_info is None:
        endpoint = _get_addon_endpoint()
        response = ayon_api.get(f"{endpoint}/files_info")
        response.raise_for_status()
        _ThirdPartyCache.server_files_info = response.data
    return copy.deepcopy(_ThirdPartyCache.server_files_info)


def _makedirs(path: str) -> None:
    """Create directory if not exists.

    Do not execute 'os.makedirs' if directory already exists, to avoid
    possible permissions issues.

    Args:
        path (str): Directory that should be created.

    """
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def _check_args_returncode(args: list[str]) -> bool:
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


def validate_ffmpeg_args(args: list[str]) -> bool:
    """Validate ffmpeg arguments.

    Args:
        args (list[str]): ffmpeg arguments.

    Returns:
        bool: True if arguments are valid.

    """
    if not args:
        return False
    return _check_args_returncode(args + ["-version"])


def validate_oiio_args(args: list[str]) -> bool:
    """Validate oiio arguments.

    Args:
        args (list[str]): oiio arguments.

    Returns:
        bool: True if arguments are valid.

    """
    if not args:
        return False
    return _check_args_returncode(args + ["--help"])


def _homebrew_get_tool_path(
    package_name: str, tool_name: str
) -> str | None:
    try:
        brew_prefix = subprocess.check_output(
            ["brew", "--prefix", package_name],
            text=True,
            stderr=subprocess.DEVNULL
        ).strip()
        tool_root = os.path.join(brew_prefix, "bin")
        tool_path = os.path.join(tool_root, tool_name)
        if os.path.exists(tool_path):
            return tool_path

    except (subprocess.CalledProcessError, Exception):
        log.info("Failed to get 'ffmpeg' prefix from homebrew")
    return None


def _homebrew_install(package_name: str, tool_name: str) -> str | None:
    """Install tool using homebrew.

    This function does not validate the installed version. It could use very
        old or very new version of ffmpeg.

    Returns:
        str | None: Path to tool if installed.

    """
    if PLATFORM_NAME != "darwin":
        return None

    tool_path = _homebrew_get_tool_path(package_name, tool_name)
    if tool_path:
        return tool_path

    log.info(f"Installing '{tool_name}' using homebrew.")
    try:
        subprocess.check_call(["brew", "install", package_name])
    except subprocess.CalledProcessError:
        log.error(f"Failed to install '{package_name}' using homebrew.")
        return None

    return _homebrew_get_tool_path(package_name, tool_name)


def _winget_get_ffmpeg_path(
    package_id: str,
    tool_filename: str,
) -> str | None:
    """Find path to tool installed via winget.

    Args:
        package_id (str): WinGet package ID.

    Returns:
        str | None: Path to tool if found.

    """
    packages_dirs: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        path = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if path.is_dir():
            packages_dirs.append(path)

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        path = Path(program_files) / "WinGet" / "Packages"
        if path.is_dir():
            packages_dirs.append(path)

    if not packages_dirs:
        return None

    filtered_dirs = []
    for packages_dir in packages_dirs:
        for package_dir in packages_dir.iterdir():
            if (
                package_dir.is_dir()
                and package_id in package_dir.name
            ):
                filtered_dirs.append(package_dir)

    for package_dir in filtered_dirs:
        for subdir in package_dir.iterdir():
            subdir /= "bin"
            if not subdir.is_dir():
                continue

            for subfile in subdir.iterdir():
                if subfile.is_file() and subfile.name == "ffmpeg.exe":
                    return str(subdir.absolute() / tool_filename)
    return None


def _winget_install_ffmpeg() -> str | None:
    """Install ffmpeg using winget.

    Returns:
        str | None: Path to tool if installed.

    """
    if PLATFORM_NAME != "windows":
        return None

    # Check if already installed via winget
    tool_path = _winget_get_ffmpeg_path(WINGET_FFMPEG_PACKAGE, "ffmpeg.exe")
    if tool_path:
        return os.path.dirname(tool_path)

    try:
        subprocess.check_call([
            "winget", "install",
            "-e", "--id", WINGET_FFMPEG_PACKAGE
        ])
    except subprocess.CalledProcessError:
        log.error("Failed to install 'ffmpeg' using winget.")
        return None

    tool_path = _winget_get_ffmpeg_path(WINGET_FFMPEG_PACKAGE, "ffmpeg.exe")
    if tool_path:
        return os.path.dirname(tool_path)
    return None


def _get_resources_dir(*args) -> str:
    return get_addons_resources_dir(ADDON_NAME, *args)


def _read_progress_file(progress_path: str):
    try:
        with open(progress_path, "r") as stream:
            return json.loads(stream.read())
    except Exception:
        return {}


def _find_file_info(
    name: str, files_info: list[ToolDownloadInfo]
) -> ToolDownloadInfo | None:
    """Find file info by name.

    Args:
        name (str): Name of file to find.
        files_info (list[ToolDownloadInfo]): List of file info dicts.

    Returns:
        ToolDownloadInfo | None: File info data.

    """
    return next(
        (
            file_info
            for file_info in files_info
            if (
                file_info["name"] == name
                and file_info["platform"] == PLATFORM_NAME
            )
        ),
        None
    )


def _get_tool_resource_dir(
    tool_name: str,
    server_files_info: list[ToolDownloadInfo] | None = None,
) -> str | None:
    if server_files_info is None:
        server_files_info = get_server_files_info()
    server_info = _find_file_info(tool_name, server_files_info)
    if not server_info:
        return None
    platform_name = server_info["platform"]
    # Use first 8 characters of checksum as directory name
    checksum = server_info["checksum"][:8]
    return _get_resources_dir(f"{tool_name}_{platform_name}_{checksum}")


def _get_downloaded_ffmpeg_root(
    server_files_info: list[ToolDownloadInfo] | None = None,
) -> str | None:
    if _FFmpegArgs.downloaded_root is NOT_SET:
        _FFmpegArgs.downloaded_root = _get_tool_resource_dir(
            "ffmpeg", server_files_info
        )
    return _FFmpegArgs.downloaded_root


def _get_downloaded_oiio_root(
    server_files_info: list[ToolDownloadInfo] | None = None,
) -> str | None:
    if _OIIOArgs.downloaded_root is NOT_SET:
        _OIIOArgs.downloaded_root = _get_tool_resource_dir(
            "oiio", server_files_info
        )
    return _OIIOArgs.downloaded_root


def _fill_ffmpeg_tool_args(
    tool_name: FFmpegToolname,
    addon_settings: dict[str, Any] | None = None,
    tracker: InstallTracker | None = None,
) -> list[str] | None:
    args = _FFmpegArgs.tools.get(tool_name, NOT_SET)
    if args is not NOT_SET:
        if tracker is not None:
            tracker.set_finished(success=args is not None)
        return args

    if tool_name not in _FFmpegArgs.tools:
        joined_tools = ", ".join([f"'{t}'" for t in _FFmpegArgs.tools])
        raise ValueError(
            f"Invalid tool name '{tool_name}'. Expected {joined_tools}"
        )

    tool_filename = tool_name
    if PLATFORM_NAME == "windows":
        tool_filename = f"{tool_name}.exe"

    if addon_settings is None:
        addon_settings = get_addon_settings()

    if tracker is None:
        tracker = InstallTracker("FFmpeg")

    tracker.set_started()
    ffmpeg_settings = addon_settings["ffmpeg"]
    for item in ffmpeg_settings[PLATFORM_NAME]:
        tracker.set_transfer_progress(None)
        receive_type = item["receive_type"]
        if receive_type == "custom_args":
            custom_args = list(item["custom_args"][tool_name])
            if not validate_ffmpeg_args(custom_args):
                continue
            tracker.set_finished()
            _FFmpegArgs.tools[tool_name] = custom_args
            return custom_args

        if receive_type == "download":
            if is_ffmpeg_download_needed(addon_settings):
                progress = TransferProgress()
                tracker.set_transfer_progress(progress)
                _download_ffmpeg(progress)

            path_parts = [_get_downloaded_ffmpeg_root()]
            if PLATFORM_NAME == "windows":
                path_parts.append("bin")
            path_parts.append(tool_filename)

            args = [
                os.path.sep.join(path_parts)
            ]
            if not validate_ffmpeg_args(args):
                continue
            tracker.set_finished()
            _FFmpegArgs.tools[tool_name] = args
            return args

        if receive_type == "custom_root":
            custom_root = item["custom_root"]
            try:
                custom_root = custom_root.format_map(os.environ)
            except (ValueError, KeyError):
                print(f"Failed to format custom root '{custom_root}'")
                continue

            tool_path = tool_filename
            if custom_root:
                tool_path = os.path.join(custom_root, tool_path)
            args = [tool_path]
            if not validate_ffmpeg_args(args):
                continue

            tracker.set_finished()
            _FFmpegArgs.tools[tool_name] = args
            return args

        if receive_type == "homebrew":
            tool_path = _homebrew_get_tool_path("ffmpeg", tool_filename)
            if tool_path:
                args = [tool_path]
                if validate_ffmpeg_args(args):
                    tracker.set_finished()
                    _FFmpegArgs.tools[tool_name] = args
                    return args

        if receive_type == "winget":
            _winget_install_ffmpeg()
            tool_path = _winget_get_ffmpeg_path(
                WINGET_FFMPEG_PACKAGE, tool_filename
            )
            if tool_path:
                args = [tool_path]
                if validate_ffmpeg_args(args):
                    tracker.set_finished()
                    _FFmpegArgs.tools[tool_name] = args
                    return args

    tracker.set_finished(success=False)
    final_args = None
    _FFmpegArgs.tools[tool_name] = final_args
    return final_args


def _fill_oiio_tool_args(
    tool_name: OIIOToolName,
    addon_settings: dict[str, Any] | None = None,
    tracker: InstallTracker | None = None,
) -> list[str] | None:
    args = _OIIOArgs.tools.get(tool_name, NOT_SET)
    if args is not NOT_SET:
        if tracker is not None:
            tracker.set_finished(success=args is not None)
        return args

    if tool_name not in _OIIOArgs.tools:
        joined_tools = ", ".join([f"'{t}'" for t in _OIIOArgs.tools])
        raise ValueError(
            f"Invalid tool name '{tool_name}'. Expected {joined_tools}"
        )

    if tracker is None:
        tracker = InstallTracker("OpenImageIO")

    if addon_settings is None:
        addon_settings = get_addon_settings()

    tool_filename = tool_name
    if PLATFORM_NAME == "windows":
        tool_filename = f"{tool_name}.exe"

    tracker.set_started()

    oiio_settings = addon_settings["oiio"]
    for item in oiio_settings[PLATFORM_NAME]:
        tracker.set_transfer_progress(None)

        receive_type = item["receive_type"]
        if receive_type == "custom_args":
            custom_args = list(oiio_settings["custom_args"][tool_name])
            if not validate_oiio_args(custom_args):
                continue
            tracker.set_finished()
            _OIIOArgs.tools[tool_name] = custom_args
            return custom_args

        if receive_type == "custom_root":
            custom_root = item["custom_root"]
            try:
                custom_root = custom_root.format_map(os.environ)
            except (ValueError, KeyError):
                print(f"Failed to format custom root '{custom_root}'")
                continue

            tool_path = tool_name
            if custom_root:
                tool_path = os.path.join(custom_root, tool_path)
            args = [tool_path]
            if not validate_oiio_args(args):
                continue

            tracker.set_finished()
            _OIIOArgs.tools[tool_name] = args
            return args

        if receive_type == "download":
            if is_oiio_download_needed(addon_settings):
                progress = TransferProgress()
                tracker.set_transfer_progress(progress)
                _download_oiio(progress)

            args = [
                os.path.sep.join(
                    _get_downloaded_oiio_root(),
                    "bin",
                    tool_filename
                )
            ]
            if not validate_oiio_args(args):
                continue
            tracker.set_finished()
            _OIIOArgs.tools[tool_name] = args
            return args

        if receive_type == "homebrew":
            tool_path = _homebrew_get_tool_path("openimageio", tool_filename)
            if tool_path:
                args = [tool_path]
                if validate_oiio_args(args):
                    tracker.set_finished()
                    _OIIOArgs.tools[tool_name] = args
                    return args

    tracker.set_finished(success=False)
    final_args = None
    _OIIOArgs.tools[tool_name] = final_args
    return final_args


def is_ffmpeg_download_needed(
    addon_settings: dict[str, Any] | None = None,
) -> bool:
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
    tool_name = tool_filename = "ffmpeg"
    if PLATFORM_NAME == "windows":
        tool_filename = "ffmpeg.exe"

    for item in ffmpeg_settings[PLATFORM_NAME]:
        receive_type = item["receive_type"]
        if receive_type == "custom_args":
            custom_args = list(item["custom_args"][tool_name])
            if not validate_ffmpeg_args(custom_args):
                continue
            _FFmpegArgs.tools[tool_name] = custom_args
            break

        if receive_type == "custom_root":
            custom_root = item["custom_root"]
            try:
                custom_root = custom_root.format_map(os.environ)
            except (ValueError, KeyError):
                print(f"Failed to format custom root '{custom_root}'")
                continue

            tool_path = tool_filename
            if custom_root:
                tool_path = os.path.join(custom_root, tool_path)
            args = [tool_path]
            if not validate_ffmpeg_args(args):
                continue

            _FFmpegArgs.tools[tool_name] = args
            break

        if receive_type == "download":
            # Check what is required by server
            ffmpeg_root = _get_downloaded_ffmpeg_root()
            progress_info = {}
            if ffmpeg_root:
                progress_path = os.path.join(
                    ffmpeg_root, DIST_PROGRESS_FILENAME
                )
                progress_info = _read_progress_file(progress_path)
            download_needed = progress_info.get("state") != "done"
            break

        if receive_type == "homebrew":
            tool_path = _homebrew_get_tool_path("ffmpeg", tool_filename)
            if not tool_path:
                download_needed = True
            break

        if receive_type == "winget":
            tool_path = _winget_get_ffmpeg_path(
                WINGET_FFMPEG_PACKAGE, tool_filename
            )
            if (
                not tool_path
                or not os.path.exists(tool_path)
            ):
                download_needed = True
            break

    _FFmpegArgs.download_needed = download_needed
    return _FFmpegArgs.download_needed


def is_oiio_download_needed(
    addon_settings: dict[str, Any] | None = None,
) -> bool:
    """Check if is download needed.

    Returns:
        bool: Should be config downloaded.

    """
    if _OIIOArgs.download_needed is not None:
        return _OIIOArgs.download_needed

    if addon_settings is None:
        addon_settings = get_addon_settings()

    oiio_settings = addon_settings["oiio"]

    tool_name = tool_filename = "oiiotool"
    if PLATFORM_NAME == "windows":
        tool_filename = "oiiotool.exe"

    download_needed = False
    for item in oiio_settings[PLATFORM_NAME]:
        receive_type = item["receive_type"]
        if receive_type == "custom_args":
            custom_args = list(oiio_settings["custom_args"][tool_name])
            if not validate_oiio_args(custom_args):
                continue
            _OIIOArgs.tools[tool_name] = custom_args
            break

        if receive_type == "custom_root":
            custom_root = item["custom_root"]
            try:
                custom_root = custom_root.format_map(os.environ)
            except (ValueError, KeyError):
                print(f"Failed to format custom root '{custom_root}'")
                continue

            tool_path = tool_name
            if custom_root:
                tool_path = os.path.join(custom_root, tool_path)
            args = [tool_path]
            if not validate_oiio_args(args):
                continue

            _OIIOArgs.tools[tool_name] = args
            break

        if receive_type == "download":
            # Check what is required by server
            ffmpeg_root = _get_downloaded_oiio_root()
            progress_info = {}
            if ffmpeg_root:
                progress_path = os.path.join(
                    ffmpeg_root, DIST_PROGRESS_FILENAME
                )
                progress_info = _read_progress_file(progress_path)
            download_needed = progress_info.get("state") != "done"
            break

        if receive_type == "homebrew":
            tool_path = _homebrew_get_tool_path("openimageio", tool_filename)
            if not tool_path or not validate_oiio_args([tool_path]):
                download_needed = True
            break

    _OIIOArgs.download_needed = download_needed
    return _OIIOArgs.download_needed


def _wait_for_other_process(progress_path: str, progress_id: str) -> bool:
    dirpath = os.path.dirname(progress_path)
    started = time.time()
    progress_existed = False
    threshold_time = None
    state = None
    while True:
        if not os.path.exists(progress_path):
            if progress_existed:
                log.debug(
                    "Other processed didn't finish download or extraction,"
                    " trying to do so."
                )
            break

        progress_info = _read_progress_file(progress_path)
        if progress_info.get("progress_id") == progress_id:
            return False

        current_state = progress_info.get("state")

        if not progress_existed:
            log.debug(
                "Other process already created progress file"
                " in target directory. Waiting for finishing it."
            )

        progress_existed = True
        if current_state is None:
            log.warning(
                "Other process did not store 'state' to progress file."
            )
            return False

        if current_state == "done":
            log.debug("Other process finished extraction.")
            return True

        if current_state != state:
            started = time.time()
            threshold_time = None
            state = current_state

        if threshold_time is None:
            threshold_time = EXTRACT_WAIT_TRESHOLD_TIME
            if current_state == "downloading":
                threshold_time = DOWNLOAD_WAIT_TRESHOLD_TIME

        if (time.time() - started) > threshold_time:
            log.debug(
                f"Waited for treshold time ({EXTRACT_WAIT_TRESHOLD_TIME}s)."
                f" Extracting downloaded content."
            )
            try:
                shutil.rmtree(dirpath)
            except PermissionError as exc:
                log.warning(
                    "Failed to remove target directory. Other process"
                    " might still be extracting content."
                )
                raise exc
            break
        time.sleep(0.1)
    return False


def _download_file(
    file_info: ToolDownloadInfo,
    dirpath: str,
    progress: TransferProgress | None = None,
) -> bool:
    filename = file_info["filename"]
    checksum = file_info["checksum"]
    checksum_algorithm = file_info["checksum_algorithm"]

    progress_path = os.path.join(dirpath, DIST_PROGRESS_FILENAME)
    progress_id = uuid.uuid4().hex
    already_done = _wait_for_other_process(progress_path, progress_id)
    if already_done:
        return False

    _makedirs(dirpath)
    progress_info = {
        "state": "downloading",
        "progress_id": progress_id,
        "checksum": checksum,
        "checksum_algorithm": checksum_algorithm,
        "dist_started": (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ),
    }
    with open(progress_path, "w") as stream:
        json.dump(progress_info, stream)

    tmpdir = tempfile.mkdtemp(prefix=ADDON_NAME)
    finished = False
    try:
        archive_filepath = ayon_api.download_addon_private_file(
            ADDON_NAME,
            __version__,
            filename,
            tmpdir,
            progress=progress
        )

        if not validate_file_checksum(
            archive_filepath, checksum, checksum_algorithm
        ):
            raise ValueError(
                "Downloaded file hash does not match expected hash"
            )

        # Find out if something else already downloaded and extracted
        # NOTE This is primitive validation. We might also want to not start
        #   downloading at first place? - That would require to store download
        #   progress somewhere to avoid stale download.
        already_done = _wait_for_other_process(progress_path, progress_id)
        if already_done:
            return False

        # Store progress so any other processes know that this was
        #   downloaded
        _makedirs(dirpath)
        progress_info["state"] = "extracting"
        with open(progress_path, "w") as stream:
            json.dump(progress_info, stream)

        log.debug(f"Extracting '{archive_filepath}' to '{dirpath}'.")
        extract_archive_file(archive_filepath, dirpath)

        finished = True
        current_progress_info = _read_progress_file(progress_path)
        if current_progress_info.get("progress_id") != progress_id:
            return False

        progress_info["state"] = "done"
        progress_info["dist_finished"] = (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        with open(progress_path, "w") as stream:
            json.dump(progress_info, stream)

    finally:
        if os.path.exists(tmpdir):
            shutil.rmtree(tmpdir)

        if not finished:
            progress_info = _read_progress_file(progress_path)
            if progress_info.get("progress_id") == progress_id:
                os.remove(progress_path)

    return True


def _download_ffmpeg(
    progress: TransferProgress | None = None,
) -> None:
    """Download ffmpeg from server.

    Todos:
        Add safeguard to avoid downloading of the file from multiple
            processes at once.

    Args:
        progress (ayon_api.TransferProgress): Keep track about download.

    """

    files_info = get_server_files_info()
    file_info = _find_file_info("ffmpeg", files_info)
    if file_info is None:
        raise ValueError((
            "Couldn't find ffmpeg source file for platform '{}'"
        ).format(platform.system()))

    dirpath = _get_downloaded_ffmpeg_root()
    log.debug(f"Downloading ffmpeg into: '{dirpath}'")
    if not _download_file(file_info, dirpath, progress=progress):
        log.debug("Other processed already downloaded and extracted ffmpeg.")

    _FFmpegArgs.download_needed = False
    _FFmpegArgs.downloaded_root = NOT_SET


def _download_oiio(progress: TransferProgress | None = None) -> None:
    files_info = get_server_files_info()
    file_info = _find_file_info("oiio", files_info)
    if file_info is None:
        raise ValueError((
            "Couldn't find OpenImageIO source file for platform '{}'"
        ).format(platform.system()))

    dirpath = _get_downloaded_oiio_root()
    log.debug("Downloading OIIO into: '%s'", dirpath)
    if not _download_file(file_info, dirpath, progress=progress):
        log.debug("Other processed already downloaded and extracted OIIO.")

    _OIIOArgs.download_needed = False
    _OIIOArgs.downloaded_root = NOT_SET


def install_ffmpeg(
    tracker: InstallTracker | None = None,
    addon_settings: dict[str, Any] | None = None,
) -> None:
    """Install FFmpeg."""
    _fill_ffmpeg_tool_args(
        "ffmpeg",
        tracker=tracker,
        addon_settings=addon_settings,
    )


def install_oiio(
    tracker: InstallTracker | None = None,
    addon_settings: dict[str, Any] | None = None,
) -> None:
    """Install OpenImageIO."""
    _fill_oiio_tool_args(
        "oiiotool",
        tracker=tracker,
        addon_settings=addon_settings,
    )


def get_ffmpeg_arguments(
    tool_name: FFmpegToolname = "ffmpeg"
) -> list[str] | None:
    """Get arguments to run one of ffmpeg tools.

    Args:
        tool_name (FFmpegToolname): Name of
            tool for which arguments should be returned.

    Returns:
        list[str]: Path to FFmpeg directory.

    """
    args = _FFmpegArgs.tools.get(tool_name, NOT_SET)
    if args is NOT_SET:
        args = _fill_ffmpeg_tool_args(tool_name)
    return copy.deepcopy(args)


def get_oiio_arguments(
    tool_name: OIIOToolName = "oiiotool"
) -> list[str] | None:
    """Get arguments to run one of OpenImageIO tools.

    Possible OIIO tools:
        oiiotool, maketx, iv, iinfo, igrep, idiff, iconvert

    Args:
        tool_name (OIIOToolName): Name of OIIO tool.

    Returns:
        str: Path to zip info file.

    """
    args = _OIIOArgs.tools.get(tool_name, NOT_SET)
    if args is NOT_SET:
        args = _fill_oiio_tool_args(tool_name)
    return copy.deepcopy(args)
