from __future__ import annotations

from copy import deepcopy
from typing import Any

PLATFORM_NAMES = (
    "windows",
    "linux",
    "darwin",
)


def _convert_tools_settings_1_5_0(
    tool_overrides: dict[str, Any] | None,
    tool_names: list[str],
) -> None:
    if not tool_overrides:
        return

    use_downloaded = tool_overrides.pop("use_downloaded", None)
    custom_args = tool_overrides.pop("custom_args", None)
    custom_roots = tool_overrides.pop("custom_roots", None)
    if (
        use_downloaded is None
        and custom_args is None
        and custom_roots is None
    ):
        return

    for platform_name in PLATFORM_NAMES:
        if platform_name in tool_overrides:
            return

    if custom_args is None:
        custom_args = {}

    if custom_roots is None:
        custom_roots = {}

    if use_downloaded is None:
        use_downloaded = True

    windows_items = []
    linux_items = []
    darwin_items = []
    for pname in PLATFORM_NAMES:
        if pname not in custom_roots:
            continue

        if pname == "windows":
            _items = windows_items
        elif pname == "linux":
            _items = linux_items
        elif pname == "darwin":
            _items = darwin_items
        else:
            continue

        for root in custom_roots[pname]:
            if root:
                _items.append({
                    "receive_type": "custom_root",
                    "custom_root": root,
                })

    # There is no platform specific information in custom args, so they are
    #   added for each platform.
    args_by_tool_name = {}
    max_args_length = 0
    for tool_name in tool_names:
        items = custom_args.get(tool_name) or []
        filtered_args = [
            item["args"]
            for item in items
            if item.get("args")
        ]
        args_by_tool_name[tool_name] = filtered_args
        max_args_length = max(max_args_length, len(filtered_args))

    for _ in range(max_args_length):
        custom_args = {}
        for tool_name in tool_names:
            tool_args = args_by_tool_name[tool_name]
            args = []
            if tool_args:
                args = tool_args.pop(0)
            custom_args[tool_name] = args

        windows_items.append({
            "receive_type": "custom_args",
            "custom_args": deepcopy(custom_args),
        })
        linux_items.append({
            "receive_type": "custom_args",
            "custom_args": deepcopy(custom_args),
        })
        darwin_items.append({
            "receive_type": "custom_args",
            "custom_args": deepcopy(custom_args),
        })

    if use_downloaded:
        windows_items.append({"receive_type": "download"})
        linux_items.append({"receive_type": "download"})
        darwin_items.append({"receive_type": "download"})

    for pname, items in (
        ("windows", windows_items),
        ("linux", linux_items),
        ("darwin", darwin_items),
    ):
        if items:
            tool_overrides[pname] = items


def _convert_settings_1_5_0(overrides):
    if not overrides:
        return

    _convert_tools_settings_1_5_0(
        overrides.get("ffmpeg"),
        ["ffmpeg", "ffprobe"],
    )
    _convert_tools_settings_1_5_0(
        overrides.get("oiio"),
        ["oiiotool", "maketx", "iv", "iinfo", "igrep", "idiff", "iconvert"]
    )


def convert_settings_overrides(
    source_version: str,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    _convert_settings_1_5_0(overrides)
    return overrides
