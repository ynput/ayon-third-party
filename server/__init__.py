import os
import json

from fastapi import Depends

from ayon_server.addons import BaseServerAddon
from ayon_server.api.dependencies import dep_current_user
from ayon_server.entities import UserEntity

from .version import __version__
from .settings import ThirdPartySettings

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


class ThirdPartyDistAddon(BaseServerAddon):
    name = "ayon_third_party"
    title = "3rd Party Distribution"
    version = __version__
    settings_model = ThirdPartySettings

    def initialize(self):
        self.add_endpoint(
            "files_info",
            self._get_files_info,
            method="GET",
            name="files_info",
            description="Get information about binary files on server.",
        )

    async def _get_files_info(
        self,
        user: UserEntity = Depends(dep_current_user)
    ) -> list[dict[str, str]]:
        info_filepath = os.path.join(
            CURRENT_DIR, "private", "files_info.json"
        )
        with open(info_filepath, "r") as stream:
            data = json.load(stream)
        return data
