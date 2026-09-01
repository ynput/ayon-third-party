import os
import json
from typing import Any

from fastapi import Depends

from ayon_server.addons import BaseServerAddon
from ayon_server.api.dependencies import dep_current_user
from ayon_server.entities import UserEntity

from .settings import (
    convert_settings_overrides,
    ThirdPartySettings,
    DEFAULT_SETTINGS,
)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


class ThirdPartyDistAddon(BaseServerAddon):
    settings_model = ThirdPartySettings

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_SETTINGS)

    async def convert_settings_overrides(
        self,
        source_version: str,
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        convert_settings_overrides(source_version, overrides)
        # Use super conversion
        return await super().convert_settings_overrides(
            source_version, overrides
        )


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
            os.path.dirname(CURRENT_DIR), "private", "files_info.json"
        )
        with open(info_filepath, "r") as stream:
            data = json.load(stream)
        return data
