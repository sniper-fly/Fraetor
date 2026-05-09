from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import SSOTokenLoadError, UnauthorizedSSOTokenError
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient


_ENV_AZURE_SPEECH_KEY = "FRAETOR_SSM_AZURE_SPEECH_KEY"
_ENV_MAI_API_KEY = "FRAETOR_SSM_MAI_API_KEY"
_ENV_MAI_ENDPOINT = "FRAETOR_SSM_MAI_ENDPOINT"
_ENV_VERTEX_SA = "FRAETOR_SSM_VERTEX_SA"

_ENV_VARS = (
    _ENV_AZURE_SPEECH_KEY,
    _ENV_MAI_API_KEY,
    _ENV_MAI_ENDPOINT,
    _ENV_VERTEX_SA,
)

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


def _resolve_param_names() -> tuple[str, str, str, str]:
    missing = [name for name in _ENV_VARS if not os.environ.get(name)]
    if missing:
        msg = f"環境変数が未設定です: {missing}"
        raise RuntimeError(msg)
    return (
        os.environ[_ENV_AZURE_SPEECH_KEY],
        os.environ[_ENV_MAI_API_KEY],
        os.environ[_ENV_MAI_ENDPOINT],
        os.environ[_ENV_VERTEX_SA],
    )


def load_secrets(client: SSMClient | None = None) -> Secrets:
    """AWS SSM Parameter Store から SecureString を一括取得して Secrets を返す。

    SSM パラメータ名は環境変数 FRAETOR_SSM_* から解決する。
    AWS_PROFILE / AWS_REGION 環境変数に従う。SSO セッション切れ時は
    `aws sso login` を案内する RuntimeError を送出する。
    """
    azure_path, mai_key_path, mai_endpoint_path, vertex_sa_path = _resolve_param_names()
    param_names = [azure_path, mai_key_path, mai_endpoint_path, vertex_sa_path]

    ssm = client if client is not None else boto3.client("ssm")
    try:
        response = ssm.get_parameters(
            Names=param_names,
            WithDecryption=True,
        )
    except (SSOTokenLoadError, UnauthorizedSSOTokenError) as exc:
        raise RuntimeError(_SSO_LOGIN_HINT) from exc

    invalid = response.get("InvalidParameters", [])
    if invalid:
        msg = f"SSM パラメータが見つかりません: {invalid}"
        raise RuntimeError(msg)

    values = {p["Name"]: p["Value"] for p in response["Parameters"]}

    sa_raw = values[vertex_sa_path]
    try:
        vertex_sa_info: dict[str, Any] = json.loads(sa_raw)
    except json.JSONDecodeError as exc:
        msg = f"Vertex SA JSON のパースに失敗しました: {exc}"
        raise RuntimeError(msg) from exc

    return Secrets(
        azure_speech_key=values[azure_path],
        mai_api_key=values[mai_key_path],
        mai_endpoint=values[mai_endpoint_path],
        vertex_sa_info=vertex_sa_info,
        vertex_project=str(vertex_sa_info.get("project_id", "")),
    )
