from openpype.modules import OpenPypeModule, ITrayModule

from .constants import ADDON_NAME
from .version import __version__


class ThirdPartyDistAddon(OpenPypeModule, ITrayModule):
    """Addon to deploy 3rd party binary dependencies.

    Addon can also skip distribution of binaries from server and can
    use path/arguments defined by server.

    Cares about supplying ffmpeg and oiiotool executables.
    """

    name = ADDON_NAME
    version = __version__
    # Class cache if download is needed

    def initialize(self, module_settings):
        self.enabled = True

    def tray_exit(self):
        pass

    def tray_menu(self, tray_menu):
        pass

    def tray_init(self):
        pass

    def tray_start(self):
        pass
