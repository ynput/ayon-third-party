from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
)

from .ffmpeg import FFmpegSettings
from .oiio import OIIOSettings


class ThirdPartySettings(BaseSettingsModel):
    """Third party addon settings."""

    ffmpeg: FFmpegSettings = SettingsField(
        default_factory=FFmpegSettings,
        title="FFmpeg",
    )
    oiio: OIIOSettings = SettingsField(
        default_factory=OIIOSettings,
        title="OpenImageIO",
    )


DEFAULT_SETTINGS = {
    "ffmpeg": {
        "windows": [
            {
                "receive_type": "download",
            },
        ],
        "linux": [
            {
                "receive_type": "download",
            },
        ],
        "darwin": [],
    },
    "oiio": {
        "windows": [
            {
                "receive_type": "download",
            },
        ],
        "linux": [
            {
                "receive_type": "download",
            },
        ],
        "darwin": [],
    },
}