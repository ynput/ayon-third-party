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
from typing import Optional, Tuple, List, Dict, Any

import ayon_api
from ayon_api import TransferProgress

from ayon_core.lib import Logger, CacheItem
try:
    from ayon_core.lib import get_launcher_storage_dir
except ImportError:
    from ayon_core.lib import get_ayon_appdirs as get_launcher_storage_dir

from .version import __version__
from .constants import ADDON_NAME

if typing.TYPE_CHECKING:
    from typing import Literal, TypedDict

    OIIOToolName = Literal[
        "oiiotool", "maketx", "iv", "iinfo", "igrep", "idiff", "iconvert"
    ]
    FFmpegToolname = Literal["ffmpeg", "ffprobe"]


    class ToolInfo(TypedDict):
        root: str
        checksum: str
        checksum_algorithm: str
        downloaded: str


    class ToolDownloadInfo(TypedDict):
        name: Literal["ffmpeg", "oiio"]
        filename: str
        checksum: str
        checksum_algorithm: str
        platform: Literal["windows", "linux", "darwin"]


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEPRECATED_DOWNLOAD_DIR = os.path.join(
    CURRENT_DIR, "downloads", platform.system().lower()
)
NOT_SET = type("NOT_SET", (), {"__bool__": lambda: False})()
IMPLEMENTED_ARCHIVE_FORMATS = {
    ".zip", ".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"
}
# Filename where is stored progress of extraction
DIST_PROGRESS_FILENAME = "dist_progress.json"
# How long to wait for other process to download/extract content
DOWNLOAD_WAIT_TRESHOLD_TIME = 20
EXTRACT_WAIT_TRESHOLD_TIME = 20

log = Logger.get_logger(__name__)


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
) -> Tuple[Optional[str], Optional[str]]:
    """Get archive extension and type.

    Args:
        archive_file (str): Path to archive file.

    Returns:
        Tuple[str, str]: Archive extension and type.

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
    dst_folder: Optional[str] = None,
):
    """Extract archived file to a directory.

    Args:
        archive_file (str): Path to a archive file.
        dst_folder (Optional[str]): Directory where content will be extracted.
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


def get_addon_settings():
    if not _ThirdPartyCache.addon_settings.is_valid:
        _ThirdPartyCache.addon_settings.update_data(
            ayon_api.get_addon_settings(
                ADDON_NAME, __version__
            )
        )
    return copy.deepcopy(_ThirdPartyCache.addon_settings.get_data())


def _get_addon_endpoint() -> str:
    return f"addons/{ADDON_NAME}/{__version__}"


def get_server_files_info() -> List["ToolDownloadInfo"]:
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


def _makedirs(path: str):
    """Create directory if not exists.

    Do not execute 'os.makedirs' if directory already exists, to avoid
    possible permissions issues.

    Args:
        path (str): Directory that should be created.

    """
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def _get_download_dir(create_if_missing: bool = True) -> str:
    """Dir path where files are downloaded.

    DEPRECATED: Use relative path to addon resource dirs.
    """
    if create_if_missing:
        _makedirs(_DEPRECATED_DOWNLOAD_DIR)
    return _DEPRECATED_DOWNLOAD_DIR


def _check_args_returncode(args: List[str]) -> bool:
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


def validate_ffmpeg_args(args: List[str]) -> bool:
    """Validate ffmpeg arguments.

    Args:
        args (list[str]): ffmpeg arguments.

    Returns:
        bool: True if arguments are valid.

    """
    if not args:
        return False
    return _check_args_returncode(args + ["-version"])


def validate_oiio_args(args: List[str]) -> bool:
    """Validate oiio arguments.

    Args:
        args (list[str]): oiio arguments.

    Returns:
        bool: True if arguments are valid.

    """
    if not args:
        return False
    return _check_args_returncode(args + ["--help"])


def _get_resources_dir(*args) -> str:
    # TODO use helper function from ayon-core for resources directory
    #   when implemented in ayon-core addon.
    addons_resources_dir = os.getenv("AYON_ADDONS_RESOURCES_DIR")
    if addons_resources_dir:
        return os.path.join(addons_resources_dir, ADDON_NAME, *args)
    return get_launcher_storage_dir(
        "addons_resources", ADDON_NAME, *args
    )


def _get_info_path(name: str) -> str:
    return get_launcher_storage_dir(
        "addons", f"{ADDON_NAME}-{name}.json"
    )


def _filter_file_info(name: str) -> List["ToolInfo"]:
    filepath = _get_info_path(name)
    try:
        if os.path.exists(filepath):
            with open(filepath, "r") as stream:
                return json.load(stream)
    except Exception:
        print(f"Failed to load {name} info from {filepath}")
    return []


def _store_file_info(name: str, info: List["ToolInfo"]):
    filepath = _get_info_path(name)
    root, filename = os.path.split(filepath)
    _makedirs(root)
    with open(filepath, "w") as stream:
        json.dump(info, stream)


def _get_downloaded_oiio_info() -> List["ToolInfo"]:
    return _filter_file_info("oiio")


def _store_downloaded_oiio_info(oiio_info: List["ToolInfo"]):
    _store_file_info("oiio", oiio_info)


def _read_progress_file(progress_path: str):
    try:
        with open(progress_path, "r") as stream:
            return json.loads(stream.read())
    except Exception:
        return {}


def _find_file_info(
    name: str, files_info: List["ToolDownloadInfo"]
) -> Optional["ToolDownloadInfo"]:
    """Find file info by name.

    Args:
        name (str): Name of file to find.
        files_info (List[ToolDownloadInfo]): List of file info dicts.

    Returns:
        Optional[ToolDownloadInfo]: File info data.

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


def _get_downloaded_root(
    name: str,
    downloaded_info: List["ToolInfo"],
    server_files_info: Optional[Dict[str, Any]],
) -> Optional[str]:
    if server_files_info is None:
        server_files_info = get_server_files_info()
    server_info = _find_file_info(name, server_files_info)
    if not server_info:
        return None

    checksum = server_info["checksum"]
    for existing_info in downloaded_info:
        if existing_info["checksum"] != checksum:
            continue

        root = existing_info["root"]
        if root and os.path.exists(root):
            return root
    return None


def get_downloaded_ffmpeg_root(
    server_files_info: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    if _FFmpegArgs.downloaded_root is NOT_SET:
        if server_files_info is None:
            server_files_info = get_server_files_info()
        server_info = _find_file_info("ffmpeg", server_files_info)
        path = None
        if server_info:
            platform_name = server_info["platform"]
            # Use first 8 characters of checksum as directory name
            checksum = server_info["checksum"][:8]
            path = _get_resources_dir(f"ffmpeg_{platform_name}_{checksum}")
        _FFmpegArgs.downloaded_root = path
    return _FFmpegArgs.downloaded_root


def get_downloaded_oiio_root(
    server_files_info: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    if _OIIOArgs.downloaded_root is NOT_SET:
        _OIIOArgs.downloaded_root = _get_downloaded_root(
            "oiio",
            _get_downloaded_oiio_info(),
            server_files_info
        )
    return _OIIOArgs.downloaded_root


def _fill_ffmpeg_tool_args(
    tool_name: "FFmpegToolname",
    addon_settings: Optional[Dict[str, Any]] = None,
) -> Optional[List[str]]:
    if tool_name not in _FFmpegArgs.tools:
        joined_tools = ", ".join([f"'{t}'" for t in _FFmpegArgs.tools])
        raise ValueError(
            f"Invalid tool name '{tool_name}'. Expected {joined_tools}"
        )

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
            tool_name = f"{tool_name}.exe"
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


def _fill_oiio_tool_args(
    tool_name: "OIIOToolName",
    addon_settings: Optional[Dict[str, Any]] = None,
) -> Optional[List[str]]:
    if tool_name not in _OIIOArgs.tools:
        joined_tools = ", ".join([f"'{t}'" for t in _OIIOArgs.tools])
        raise ValueError(
            f"Invalid tool name '{tool_name}'. Expected {joined_tools}"
        )

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
            tool_name = f"{tool_name}.exe"
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
            print(f"Failed to format root '{root}'")

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


def is_ffmpeg_download_needed(
    addon_settings: Optional[Dict[str, Any]] = None
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
    if ffmpeg_settings["use_downloaded"]:
        # Check what is required by server
        ffmpeg_root = get_downloaded_ffmpeg_root()
        progress_info = {}
        if ffmpeg_root:
            progress_path = os.path.join(
                ffmpeg_root, DIST_PROGRESS_FILENAME
            )
            progress_info = _read_progress_file(progress_path)
        download_needed = progress_info.get("state") != "done"

    _FFmpegArgs.download_needed = download_needed
    return _FFmpegArgs.download_needed


def is_oiio_download_needed(
    addon_settings: Optional[Dict[str, Any]] = None
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

    download_needed = False
    if oiio_settings["use_downloaded"]:
        oiio_root = get_downloaded_oiio_root()
        download_needed = not bool(oiio_root)
    _OIIOArgs.download_needed = download_needed
    return _OIIOArgs.download_needed


def _wait_for_other_process(progress_path: str, progress_id: str):
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

        if threshold_time is None:
            threshold_time = EXTRACT_WAIT_TRESHOLD_TIME
            if current_state == "downloading":
                threshold_time = DOWNLOAD_WAIT_TRESHOLD_TIME

        if (time.time() - started) > threshold_time:
            log.debug(
                f"Waited for treshold time ({EXTRACT_WAIT_TRESHOLD_TIME}s)."
                f" Extracting downloaded content."
            )
            shutil.rmtree(dirpath)
            break
        time.sleep(0.1)
    return False


def _download_file(
    file_info: "ToolDownloadInfo",
    dirpath: str,
    progress: Optional[TransferProgress] = None,
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


def download_ffmpeg(
    progress: Optional[TransferProgress] = None,
):
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

    dirpath = get_downloaded_ffmpeg_root()
    log.debug(f"Downloading ffmpeg into: '{dirpath}'")
    if not _download_file(file_info, dirpath, progress=progress):
        log.debug("Other processed already downloaded and extracted ffmpeg.")

    _FFmpegArgs.download_needed = False
    _FFmpegArgs.downloaded_root = NOT_SET


def download_oiio(progress: Optional[TransferProgress] = None):
    dirpath = os.path.join(_get_download_dir(), "oiio")

    files_info = get_server_files_info()
    file_info = _find_file_info("oiio", files_info)
    if file_info is None:
        raise ValueError((
            "Couldn't find OpenImageIO source file for platform '{}'"
        ).format(platform.system()))

    log.debug("Downloading OIIO into: '%s'", dirpath)
    if not _download_file(file_info, dirpath, progress=progress):
        log.debug("Other processed already downloaded and extracted OIIO.")
        _OIIOArgs.download_needed = False
        _OIIOArgs.downloaded_root = NOT_SET
        return

    oiio_info = _get_downloaded_oiio_info()
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
    _store_downloaded_oiio_info(oiio_info)
    log.debug("Stored metadata about downloaded OIIO.")

    _OIIOArgs.download_needed = False
    _OIIOArgs.downloaded_root = NOT_SET


def get_ffmpeg_arguments(
    tool_name: "FFmpegToolname" = "ffmpeg"
) -> Optional[List[str]]:
    """Get arguments to run one of ffmpeg tools.

    Args:
        tool_name (FFmpegToolname): Name of
            tool for which arguments should be returned.

    Returns:
        list[str]: Path to OpenImageIO directory.

    """
    args = _FFmpegArgs.tools.get(tool_name, NOT_SET)
    if args is NOT_SET:
        args = _fill_ffmpeg_tool_args(tool_name)
    return copy.deepcopy(args)


def get_oiio_arguments(
    tool_name: "OIIOToolName" = "oiiotool"
) -> Optional[List[str]]:
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
