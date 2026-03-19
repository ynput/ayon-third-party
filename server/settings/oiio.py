from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
)


class CustomOIIOArgumentsModel(BaseSettingsModel):
    oiiotool: list[str] = SettingsField(
        default_factory=list,
        title="*Tool 'oiiotool'"
    )
    maketx: list[str] = SettingsField(
        default_factory=list,
        title="*Tool 'maketx'"
    )
    iv: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'iv'"
    )
    iinfo: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'iinfo'"
    )
    igrep: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'igrep'"
    )
    idiff: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'idiff'"
    )
    iconvert: list[str] = SettingsField(
        default_factory=list,
        title="Tool 'iconvert'"
    )


def _openimageio_windows_enum():
    return [
        {"value": "download", "label": "Download from AYON server"},
        {"value": "custom_root", "label": "Custom root"},
        {"value": "custom_args", "label": "Custom arguments"},
    ]


def _openimageio_linux_enum():
    return [
        {"value": "download", "label": "Download from AYON server"},
        {"value": "custom_root", "label": "Custom root"},
        {"value": "custom_args", "label": "Custom arguments"},
    ]


def _openimageio_macos_enum():
    return [
        {"value": "homebrew", "label": "Install with Homebrew"},
        {"value": "custom_root", "label": "Custom root"},
        {"value": "custom_args", "label": "Custom arguments"},
    ]


class OIIOWindowsModel(BaseSettingsModel):
    _layout = "compact"
    receive_type: str = SettingsField(
        title="Receive type",
        enum_resolver=_openimageio_windows_enum,
        default="download",
        conditionalEnum=True,
    )
    custom_root: str = SettingsField(
        default_factory=str,
        title="Custom root",
        description="Root to directory where OIIO binaries can be found",
    )
    custom_args: CustomOIIOArgumentsModel = SettingsField(
        default_factory=CustomOIIOArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch OIIO tools"
        ),
    )



class OIIOLinuxModel(BaseSettingsModel):
    _layout = "compact"
    receive_type: str = SettingsField(
        title="Receive type",
        enum_resolver=_openimageio_linux_enum,
        default="download",
        conditionalEnum=True,
    )
    custom_root: str = SettingsField(
        default_factory=str,
        title="Custom root",
        description="Root to directory where OIIO binaries can be found",
    )
    custom_args: CustomOIIOArgumentsModel = SettingsField(
        default_factory=CustomOIIOArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch OIIO tools"
        ),
    )


class OIIOMacOsModel(BaseSettingsModel):
    _layout = "compact"
    receive_type: str = SettingsField(
        title="Receive type",
        enum_resolver=_openimageio_macos_enum,
        default="homebrew",
        conditionalEnum=True,
    )
    custom_root: str = SettingsField(
        "",
        title="Custom root",
        description="Root to directory where OIIO binaries can be found",
    )
    custom_args: CustomOIIOArgumentsModel = SettingsField(
        default_factory=CustomOIIOArgumentsModel,
        title="Custom arguments",
        description=(
            "Custom arguments that will be used to launch OIIO tools"
        ),
    )


class OIIOSettings(BaseSettingsModel):
    windows: list[OIIOWindowsModel] = SettingsField(
        default_factory=list,
        title="Windows",
    )
    linux: list[OIIOLinuxModel] = SettingsField(
        default_factory=list,
        title="Linux",
    )
    darwin: list[OIIOMacOsModel] = SettingsField(
        default_factory=list,
        title="macOs",
    )
