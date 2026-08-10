from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dotenv import load_dotenv

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SERVER_PORT = 18765
_SERVER_URL = f"http://127.0.0.1:{_SERVER_PORT}"
_STARTUP_TIMEOUT_SEC = 30.0
_STARTUP_POLL_INTERVAL_SEC = 0.5
_ENV_AUDIO_FILE = "FRAETOR_AUDIO_FILE"
_AUDIO_DIR = Path(__file__).parent / "fixtures" / "audio"
_E2E_TEST_TIMEOUT_SEC = 60

load_dotenv(_PROJECT_ROOT / ".env")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """`tests/e2e/` 配下は実プロセス起動・実クラウド通信を伴うため、
    単体テスト用の `timeout=10` (pyproject.toml) より長いタイムアウトを
    個別に適用する。
    """
    for item in items:
        item.add_marker(pytest.mark.timeout(_E2E_TEST_TIMEOUT_SEC))


@pytest.fixture(autouse=True)
def _block_real_aws_calls() -> None:
    """`tests/conftest.py` の実 AWS 通信ブロックを E2E 配下でのみ解除する。

    正常系シナリオ (AWS SSM 認証) は実際の AWS SSO セッション経由での
    通信を検証する必要があるため、親 conftest の同名 autouse fixture を
    再定義して上書きする (pytest は最も近い conftest.py の定義を優先する)。
    """


def _wait_for_server(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if process.poll() is not None:
            msg = f"fraetor server process exited early (code={process.returncode})"
            raise RuntimeError(msg)
        try:
            urllib.request.urlopen(_SERVER_URL, timeout=1)
        except urllib.error.URLError:
            time.sleep(_STARTUP_POLL_INTERVAL_SEC)
            continue
        else:
            return
    msg = f"fraetor server did not become ready within {_STARTUP_TIMEOUT_SEC}s"
    raise RuntimeError(msg)


def _write_dynamic_settings(history_dir: Path, overrides: dict[str, object]) -> None:
    """起動前に `settings.jsonc` を書き、動的設定を E2E 用の値に短縮する。

    タイムアウト系は `Settings` (環境変数) ではなく `DynamicSettings`
    (設定ファイル) の管轄なので、環境変数では上書きできない。ファイルが
    既に存在すればサーバーはそれを読むため、起動前に書いておけばよい。
    無音区切り (3秒既定) より短い `silence_timeout_sec` は
    `DynamicSettings` のバリデータに弾かれるため、合わせて縮める。
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "max_session_duration_sec": 20,
        "silence_timeout_sec": 3,
        "segment_silence_sec": 1.0,
        **overrides,
    }
    (history_dir / "settings.jsonc").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )


def _start_server(
    tmp_path: Path,
    extra_env: dict[str, str],
    *,
    module: str = "src",
    settings_overrides: dict[str, object] | None = None,
) -> subprocess.Popen[bytes]:
    history_dir = tmp_path / "history"
    _write_dynamic_settings(history_dir, settings_overrides or {})
    env = {
        **os.environ,
        "FRAETOR_SERVER_PORT": str(_SERVER_PORT),
        "FRAETOR_HISTORY_DIR": str(history_dir),
        **extra_env,
    }
    process = subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=_PROJECT_ROOT,
        env=env,
    )
    _wait_for_server(process)
    return process


def _stop_server(process: subprocess.Popen[bytes]) -> None:
    # /api/shutdown は録音中なら stop_session() (実クラウド通信含む) の完了を
    # 待ってからレスポンスを返すため、短いタイムアウトだと打ち切ってしまう。
    with contextlib.suppress(urllib.error.URLError, TimeoutError):
        urllib.request.urlopen(
            urllib.request.Request(f"{_SERVER_URL}/api/shutdown", method="POST"),
            timeout=15,
        )
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
def fraetor_server(tmp_path: Path) -> Generator[str]:
    """実プロセスとして `uv run fraetor` 相当を起動し、ベースURLを返す。

    ポート・履歴ファイルは環境変数で、タイムアウト系は起動前に書き出す
    `settings.jsonc` で E2E 専用の値に短縮/隔離する。マイクは実行環境の
    デフォルト入力デバイスをそのまま使う (録音内容を検証しないシナリオ向け)。
    """
    process = _start_server(tmp_path, {})
    try:
        yield _SERVER_URL
    finally:
        _stop_server(process)


class AudioServerHandle:
    """録音済み WAV を「マイク入力」として使う実サーバーの起動ハンドル。

    `start()` 実行後は `.process` で実 `subprocess.Popen` にアクセスできる
    (プロセスの終了コード等を検証するテスト向け)。
    """

    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path
        self.process: subprocess.Popen[bytes] | None = None

    def start(
        self,
        wav_filename: str,
        *,
        extra_env: dict[str, str] | None = None,
        settings_overrides: dict[str, object] | None = None,
    ) -> str:
        wav_path = _AUDIO_DIR / wav_filename
        self.process = _start_server(
            self._tmp_path,
            {_ENV_AUDIO_FILE: str(wav_path), **(extra_env or {})},
            module="tests.e2e.e2e_entrypoint",
            settings_overrides=settings_overrides,
        )
        return _SERVER_URL

    def switch_audio(self, wav_filename: str) -> None:
        """同一プロセス内で、次回録音時に読み込むWAVファイルを切り替える。

        異なる発話内容のセッションを1プロセス内で連続して発生させ、
        session_id の取り違えを検証するテスト専用の操作
        (`tests/e2e/e2e_entrypoint.py` のテスト専用エンドポイント経由)。
        """
        urllib.request.urlopen(
            urllib.request.Request(
                f"{_SERVER_URL}/api/_test/switch-audio",
                data=json.dumps({"wav_filename": wav_filename}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )


@pytest.fixture
def fraetor_audio_server_handle(tmp_path: Path) -> Generator[AudioServerHandle]:
    """`AudioServerHandle` を提供する fixture。

    `tests/e2e/e2e_entrypoint.py` (E2E 専用のコンポジションルート) 経由で
    起動し、`AudioCapture` を `FileAudioCapture` に差し替える。本番の
    `create_audio_capture()` やハードウェアマイクには一切依存しない。
    """
    handle = AudioServerHandle(tmp_path)
    try:
        yield handle
    finally:
        if handle.process is not None:
            _stop_server(handle.process)


@pytest.fixture
def fraetor_server_with_audio(
    fraetor_audio_server_handle: AudioServerHandle,
) -> Callable[[str], str]:
    """録音済み WAV を「マイク入力」として使う実サーバーを起動するファクトリ。

    戻り値の関数は `fixtures/audio/` 配下のファイル名を受け取り、
    起動後のベースURLを返す。プロセス自体にアクセスしたいテストは
    `fraetor_audio_server_handle` を直接使う。
    """
    return fraetor_audio_server_handle.start


@pytest.fixture
def broken_audio_device_env(tmp_path: Path) -> str:
    """存在しない ALSA カードを指す `asound.conf` のパスを返す。

    サーバー起動時に `ALSA_CONFIG_PATH` としてこのパスを渡すと、
    デフォルト入力デバイスのオープンに必ず失敗する状態を再現できる。
    """
    conf_path = tmp_path / "broken_asound.conf"
    conf_path.write_text(
        "pcm.!default {\n"
        "    type hw\n"
        "    card 9999\n"
        "}\n"
        "ctl.!default {\n"
        "    type hw\n"
        "    card 9999\n"
        "}\n",
        encoding="utf-8",
    )
    return str(conf_path)


@pytest.fixture
def fraetor_server_with_broken_audio(
    broken_audio_device_env: str, tmp_path: Path
) -> Generator[str]:
    """デフォルト入力デバイスのオープンが必ず失敗する状態でサーバーを起動する。"""
    process = _start_server(tmp_path, {"ALSA_CONFIG_PATH": broken_audio_device_env})
    try:
        yield _SERVER_URL
    finally:
        _stop_server(process)
