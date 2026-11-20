"""Bark: "root" is accepted as a folder without a Drive lookup (DWD users can 404)."""

from unittest.mock import MagicMock

import pytest

from gdrive.drive_helpers import resolve_folder_id


@pytest.mark.asyncio
async def test_resolve_folder_id_accepts_root_without_lookup():
    service = MagicMock()

    assert await resolve_folder_id(service, "root") == "root"
    service.files.assert_not_called()
