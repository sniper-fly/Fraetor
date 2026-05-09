from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import SSOTokenLoadError, UnauthorizedSSOTokenError
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient


_PARAM_AZURE_SPEECH_KEY = "/pass/api/azure_stt_key"
_PARAM_MAI_API_KEY = "/pass/api/azure_mai_resource"
_PARAM_MAI_ENDPOINT = "/pass/endpoint/mai_for_stt_resource"
_PARAM_VERTEX_SA = "/pass/gc/ai_service_account"

_PARAM_NAMES = [
    _PARAM_AZURE_SPEECH_KEY,
    _PARAM_MAI_API_KEY,
    _PARAM_MAI_ENDPOINT,
    _PARAM_VERTEX_SA,
]

_SSO_LOGIN_HINT = (
    "AWS SSO セッションが切れています。"
    "`aws sso login --profile <your-profile>` を実行してください。"
)


class Secrets(BaseModel):
    model_config = ConfigDict(frozen=True)

    azure_speech_key: str
    mai_api_key: str
    mai_endpoint: str
    vertex_sa_info: dict[str, Any]
    vertex_project: str


def load_secrets(client: SSMClient | None = None) -> Secrets:
    """AWS SSM Parameter Store から SecureString を一括取得して Secrets を返す。

    AWS_PROFILE / AWS_REGION 環境変数に従う。SSO セッション切れ時は
    `aws sso login` を案内する RuntimeError を送出する。
    """
    ssm = client if client is not None else boto3.client("ssm")
    try:
        response = ssm.get_parameters(
            Names=_PARAM_NAMES,
            WithDecryption=True,
        )
    except (SSOTokenLoadError, UnauthorizedSSOTokenError) as exc:
        raise RuntimeError(_SSO_LOGIN_HINT) from exc

    invalid = response.get("InvalidParameters", [])
    if invalid:
        msg = f"SSM パラメータが見つかりません: {invalid}"
        raise RuntimeError(msg)

    values = {p["Name"]: p["Value"] for p in response["Parameters"]}

    sa_raw = values[_PARAM_VERTEX_SA]
    try:
        vertex_sa_info: dict[str, Any] = json.loads(sa_raw)
    except json.JSONDecodeError as exc:
        msg = f"Vertex SA JSON のパースに失敗しました: {exc}"
        raise RuntimeError(msg) from exc

    return Secrets(
        azure_speech_key=values[_PARAM_AZURE_SPEECH_KEY],
        mai_api_key=values[_PARAM_MAI_API_KEY],
        mai_endpoint=values[_PARAM_MAI_ENDPOINT],
        vertex_sa_info=vertex_sa_info,
        vertex_project=str(vertex_sa_info.get("project_id", "")),
    )
