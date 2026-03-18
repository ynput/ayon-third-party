from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
    MultiplatformPathListModel,
)


class CustomArgumentsItem(BaseSettingsModel):
    _layout = "expanded"
    args: list[str] = SettingsField(default_factory=list, title="Arguments")


class CustomFFmpegArgumentsModel(BaseSettingsModel):
    ffmpeg: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'ffmpeg'"
    )
    ffprobe: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'ffprobe'"
    )


def _ffmpeg_windows_enum():
    return [
        {"value": "download", "label": "Download from AYON server"},
        {"value": "custom_root", "label": "Custom root"},
        {"value": "custom_args", "label": "Custom arguments"},
    ]


def _ffmpeg_linux_enum():
    return [
        {"value": "download", "label": "Download from AYON server"},
        {"value": "custom_root", "label": "Custom root"},
        {"value": "custom_args", "label": "Custom arguments"},
    ]


def _ffmpeg_macos_enum():
    return [
        {"value": "homebrew", "label": "Install with Homebrew"},
        {"value": "custom_root", "label": "Custom root"},
        {"value": "custom_args", "label": "Custom arguments"},
    ]


class FFmpegWindowsModel(BaseSettingsModel):
    _layout = "compact"
    receive_type: str = SettingsField(
        title="Receive type",
        enum_resolver=_ffmpeg_windows_enum,
        default="download",
        conditionalEnum=True,
    )
    custom_root: str = SettingsField(
        default_factory=str,
        title="Custom root",
        description="Root to directory where ffmpeg binaries can be found",
    )
    custom_args: CustomFFmpegArgumentsModel = SettingsField(
        default_factory=CustomFFmpegArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch ffmpeg tools"
        ),
    )



class FFmpegLinuxModel(BaseSettingsModel):
    _layout = "compact"
    receive_type: str = SettingsField(
        title="Receive type",
        enum_resolver=_ffmpeg_linux_enum,
        default="download",
        conditionalEnum=True,
    )
    custom_root: str = SettingsField(
        default_factory=str,
        title="Custom root",
        description="Root to directory where ffmpeg binaries can be found",
    )
    custom_args: CustomFFmpegArgumentsModel = SettingsField(
        default_factory=CustomFFmpegArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch ffmpeg tools"
        ),
    )


class FFmpegMacOsModel(BaseSettingsModel):
    _layout = "compact"
    receive_type: str = SettingsField(
        title="Receive type",
        enum_resolver=_ffmpeg_macos_enum,
        default="homebrew",
        conditionalEnum=True,
    )
    custom_root: str = SettingsField(
        "",
        title="Custom root",
        description="Root to directory where ffmpeg binaries can be found",
    )
    custom_args: CustomFFmpegArgumentsModel = SettingsField(
        default_factory=CustomFFmpegArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch ffmpeg tools"
        ),
    )


class FFmpegSettings(BaseSettingsModel):
    windows: list[FFmpegWindowsModel] = SettingsField(
        default_factory=list,
        title="Windows",
    )
    linux: list[FFmpegLinuxModel] = SettingsField(
        default_factory=list,
        title="Linux",
    )
    darwin: list[FFmpegMacOsModel] = SettingsField(
        default_factory=list,
        title="macOs",
    )


class CustomOIIOArgumentsModel(BaseSettingsModel):
    oiiotool: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="*Tool 'oiiotool'"
    )
    maketx: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="*Tool 'maketx'"
    )
    iv: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="Tool 'iv'"
    )
    iinfo: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="Tool 'iinfo'"
    )
    igrep: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="Tool 'igrep'"
    )
    idiff: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="Tool 'idiff'"
    )
    iconvert: list[CustomArgumentsItem] = SettingsField(
        default_factory=list,
        title="Tool 'iconvert'"
    )


class OIIOSettings(BaseSettingsModel):
    use_downloaded: bool = SettingsField(
        default=True,
        title="Download OpenImageIO from server",
        description="If disabled, one of custom options must be used",
    )
    custom_roots: MultiplatformPathListModel = SettingsField(
        default_factory=MultiplatformPathListModel,
        title="Custom root",
        description=(
            "Root to directory where OpenImageIO binaries can be found"
        ),
    )
    custom_args: CustomOIIOArgumentsModel = SettingsField(
        default_factory=CustomOIIOArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch OIIO tools"
        ),
    )


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
            }
        ],
        "linux": [
            {
                "receive_type": "download",
            }
        ],
        "darwin": [],
    }
}