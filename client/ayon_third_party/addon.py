from __future__ import annotations

import typing
from typing import Optional, Any

from ayon_core.addon import AYONAddon, ITrayAddon

from .constants import ADDON_NAME
from .version import __version__
from .utils import (
    is_ffmpeg_download_needed,
    is_oiio_download_needed,
)

if typing.TYPE_CHECKING:
    from .download_ui import DownloadWindow


class ThirdPartyDistAddon(AYONAddon, ITrayAddon):
    """Addon to deploy 3rd party binary dependencies.

    Addon can also skip distribution of binaries from server and can
    use path/arguments defined by server.

    Cares about supplying ffmpeg and oiiotool executables.
    """

    name = ADDON_NAME
    version = __version__

    def initialize(self, settings: dict[str, Any]) -> None:
        self._download_window: Optional["DownloadWindow"] = None

    def tray_exit(self) -> None:
        pass

    def tray_menu(self, tray_menu) -> None:
        pass

    def tray_init(self) -> None:
        pass

    def tray_start(self) -> None:
        download_ffmpeg = is_ffmpeg_download_needed()
        download_oiio = is_oiio_download_needed()
        if not download_oiio and not download_ffmpeg:
            return

        from .download_ui import show_download_window

        download_window = show_download_window(
            download_ffmpeg, download_oiio
        )
        download_window.finished.connect(self._on_download_finish)
        download_window.start()
        self._download_window = download_window

    def _on_download_finish(self) -> None:
        self._download_window.close()
        self._download_window = None
