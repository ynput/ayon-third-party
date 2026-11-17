from __future__ import annotations

import threading
import typing
from functools import partial
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
        self._addon_settings: dict[str, Any] = settings[self.name]
        self._download_window: Optional["DownloadWindow"] = None

    def tray_exit(self) -> None:
        pass

    def tray_menu(self, tray_menu) -> None:
        pass

    def tray_init(self) -> None:
        pass

    def tray_start(self) -> None:
        threading.Thread(
            target=self._check_download_needed,
            name=f"{self.name} download check",
            daemon=True,
        ).start()

    def _check_download_needed(self) -> None:
        try:
            download_ffmpeg = is_ffmpeg_download_needed(
                addon_settings=self._addon_settings
            )
            download_oiio = is_oiio_download_needed(
                addon_settings=self._addon_settings
            )
        except Exception:
            self.log.warning(
                "Failed to check if ffmpeg or OIIO download is needed.",
                exc_info=True,
            )
            return

        if download_ffmpeg or download_oiio:
            self.execute_in_main_thread(partial(
                self._show_download_window, download_ffmpeg, download_oiio
            ))

    def _show_download_window(
        self, download_ffmpeg: bool, download_oiio: bool
    ) -> None:
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
