from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

# FastAPI はハンドラのアノテーションをランタイムに解決してリクエスト/レスポンス
# モデルを決めるため、TYPE_CHECKING ブロックに移すと解決に失敗する。
from src.shared.config.dynamic_settings import DynamicSettings  # noqa: TC001

if TYPE_CHECKING:
    from src.shared.config.ports import SettingsRepositoryPort

router = APIRouter()


@router.get("/api/settings")
async def get_settings(request: Request) -> DynamicSettings:
    settings_repository: SettingsRepositoryPort = request.app.state.settings_repository
    return settings_repository.get()


@router.get("/api/settings/stt-schema")
async def get_stt_schema(request: Request) -> dict[str, object]:
    """エンジンごとの設定項目のスキーマ (型・範囲・選択肢・既定値) を返す。

    設定画面が選択中エンジンの入力欄を組み立てるために使う。スキーマは
    ライブラリのエンジン設定モデルから生成するため、エンジンが増減しても
    ここは変わらない。表示ラベル・単位はフロント側が持つ。
    """
    schemas: dict[str, object] = request.app.state.stt_settings_schemas
    return schemas


@router.put("/api/settings")
async def update_settings(request: Request, body: DynamicSettings) -> DynamicSettings:
    """設定を全項目まとめて差し替える。

    ボディを型付きパラメータとして宣言し、バリデーションを FastAPI に委ねる。
    ハンドラ内で `model_validate()` を呼ぶと `ValidationError` が捕捉されず
    500 になるため、422 を返すにはこの形にする必要がある。
    """
    settings_repository: SettingsRepositoryPort = request.app.state.settings_repository
    settings_repository.update(body)
    return body
