from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.clipboard import copy_and_paste, copy_to_clipboard, paste


class TestCopyToClipboard:
    async def test_calls_xclip_with_selection_clipboard(self) -> None:
        """design.md: xclip でクリップボードにコピー"""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0

        with patch(
            "src.clipboard.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            await copy_to_clipboard("テスト文章")

            mock_exec.assert_called_once_with(
                "xclip",
                "-selection",
                "clipboard",
                stdin=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            mock_proc.communicate.assert_called_once_with(input="テスト文章".encode())

    async def test_raises_on_nonzero_returncode(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error msg")
        mock_proc.returncode = 1

        with (
            patch(
                "src.clipboard.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
            pytest.raises(RuntimeError, match="xclip failed"),
        ):
            await copy_to_clipboard("テスト")


class TestPaste:
    async def test_calls_xdotool_key_ctrl_v(self) -> None:
        """design.md: xdotool key ctrl+v で自動ペースト"""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0

        with patch(
            "src.clipboard.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            await paste()

            mock_exec.assert_called_once_with(
                "xdotool",
                "key",
                "ctrl+v",
                stderr=asyncio.subprocess.PIPE,
            )

    async def test_raises_on_nonzero_returncode(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error msg")
        mock_proc.returncode = 1

        with (
            patch(
                "src.clipboard.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
            pytest.raises(RuntimeError, match="xdotool failed"),
        ):
            await paste()


class TestCopyAndPaste:
    async def test_skips_on_empty_text(self) -> None:
        with patch(
            "src.clipboard.copy_to_clipboard", new_callable=AsyncMock
        ) as mock_copy:
            await copy_and_paste("")
            mock_copy.assert_not_called()

    async def test_calls_copy_then_paste(self) -> None:
        with (
            patch(
                "src.clipboard.copy_to_clipboard", new_callable=AsyncMock
            ) as mock_copy,
            patch("src.clipboard.paste", new_callable=AsyncMock) as mock_paste,
        ):
            await copy_and_paste("テスト")
            mock_copy.assert_awaited_once_with("テスト")
            mock_paste.assert_awaited_once()
