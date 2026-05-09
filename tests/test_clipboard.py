from __future__ import annotations

from unittest.mock import patch

import pyperclip
import pytest

from src.clipboard import copy_to_clipboard


class TestCopyToClipboard:
    async def test_calls_pyperclip_copy_with_text(self) -> None:
        """pyperclip.copy が指定テキストで呼ばれる"""
        with patch("src.clipboard.pyperclip.copy") as mock_copy:
            await copy_to_clipboard("テスト文章")

            mock_copy.assert_called_once_with("テスト文章")

    async def test_raises_on_pyperclip_exception(self) -> None:
        """pyperclip.copy が PyperclipException を投げる場合は RuntimeError に変換"""
        with (
            patch(
                "src.clipboard.pyperclip.copy",
                side_effect=pyperclip.PyperclipException("no clipboard backend"),
            ),
            pytest.raises(RuntimeError, match="pyperclip failed"),
        ):
            await copy_to_clipboard("テスト")
