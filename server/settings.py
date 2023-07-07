from pydantic import Field, validator

from ayon_server.settings import (
    BaseSettingsModel,
    task_types_enum,
    MultiplatformPathModel,
    MultiplatformPathListModel,
)


class CustomArgumentsItem(BaseSettingsModel):
    _layout = "expanded"
    args: list[str] = Field(default_factory=list, title="Arguments")


class CustomFFmpegArgumentsModel(BaseSettingsModel):
    ffmpeg: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'ffmpeg'"
    )
    ffprobe: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'ffprobe'"
    )


class FFmpegSettings(BaseSettingsModel):
    allow_download: bool = Field(
        default=True,
        title="Allow to download ffmpeg from server",
        description="If disabled, one of custom options must be used",
    )
    custom_roots: MultiplatformPathListModel = Field(
        default_factory=MultiplatformPathListModel,
        title="Custom root",
        description="Root to directory where ffmpeg binaries can be found",
    )
    custom_args: CustomFFmpegArgumentsModel = Field(
        default_factory=CustomFFmpegArgumentsModel,
        title="Custom arguments",
        description="Custom arguments that will be used to launch ffmpeg tools",
    )


class CustomOIIOArgumentsModel(BaseSettingsModel):
    oiiotool: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="*Tool 'oiiotool'"
    )
    maketx: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="*Tool 'maketx'"
    )
    iv: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'iv'"
    )
    iinfo: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'iinfo'"
    )
    igrep: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'igrep'"
    )
    idiff: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'idiff'"
    )
    iconvert: list[CustomArgumentsItem] = Field(
        default_factory=list,
        title="Tool 'iconvert'"
    )


class OIIOSettings(BaseSettingsModel):
    allow_download: bool = Field(
        default=True,
        title="Allow to download OpenImageIO from server",
        description="If disabled, one of custom options must be used",
    )
    custom_roots: MultiplatformPathListModel = Field(
        default_factory=MultiplatformPathListModel,
        title="Custom root",
        description="Root to directory where OpenImageIO binaries can be found",
    )
    custom_sources: CustomOIIOArgumentsModel = Field(
        default_factory=CustomOIIOArgumentsModel,
        title="Custom arguments",
        description="Custom arguments that will be used to launch ffmpeg tools",
    )



class ThirdPartySettings(BaseSettingsModel):
    """Third party addon settings."""

    ffmpeg: FFmpegSettings = Field(
        default_factory=FFmpegSettings,
        title="FFmpeg",
    )
    oiio: OIIOSettings = Field(
        default_factory=OIIOSettings,
        title="OpenImageIO",
    )