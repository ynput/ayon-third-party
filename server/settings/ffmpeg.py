from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
)


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
        {"value": "winget", "label": "Install with WinGet"},
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
        {"value": "download", "label": "Download from AYON server"},
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
