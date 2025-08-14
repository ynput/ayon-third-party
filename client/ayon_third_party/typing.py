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
