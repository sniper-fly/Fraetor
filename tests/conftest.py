from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from botocore.endpoint import Endpoint

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_app_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`history_dir` を tmp_path に隔離する。

    `Settings.history_dir` は履歴 (`history.jsonl`) と動的設定
    (`settings.jsonc`) の置き場所を兼ねる。`Container` を構築するテストは
    `JsoncSettingsRepository` 経由で実ファイルを書くため、隔離しないと
    利用者の `~/.voice-input/` を書き換えてしまう。
    """
    monkeypatch.setenv("FRAETOR_HISTORY_DIR", str(tmp_path / "app-data"))


@pytest.fixture(autouse=True)
def _block_real_aws_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """テスト中の AWS への実 HTTP 通信をブロックする。

    `botocore.endpoint.Endpoint.make_request` は botocore が AWS へ HTTP
    リクエストを送る最終地点。Stubber は `before-call` イベントで応答を
    返すため make_request までは到達せず、本ガードの影響を受けない。
    monkeypatch を忘れたまま実 boto3 client が API を呼んだ場合のみ
    検出されて、実 AWS リソースへのアクセスを未然に防ぐ。
    """

    def guard(self: Endpoint, operation_model: Any, request_dict: Any) -> object:
        op = getattr(operation_model, "name", "<unknown>")
        msg = (
            f"テスト中に AWS API の実 HTTP 通信を検出: {self.host}/{op}\n"
            "Stubber か DI 経由でモッククライアントを渡してください。"
        )
        raise RuntimeError(msg)

    monkeypatch.setattr(Endpoint, "make_request", guard)
