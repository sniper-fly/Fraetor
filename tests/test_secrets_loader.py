from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import SSOTokenLoadError, UnauthorizedSSOTokenError
from botocore.stub import Stubber

from src.secrets_loader import load_secrets

if TYPE_CHECKING:
    from mypy_boto3_ssm import SSMClient


_PARAM_AZURE = "/pass/api/azure_stt_key"
_PARAM_MAI_KEY = "/pass/api/azure_mai_resource"
_PARAM_MAI_ENDPOINT = "/pass/endpoint/mai_for_stt_resource"
_PARAM_VERTEX_SA = "/pass/gc/ai_service_account"
_ALL_PARAMS = [_PARAM_AZURE, _PARAM_MAI_KEY, _PARAM_MAI_ENDPOINT, _PARAM_VERTEX_SA]

_FAKE_SA = {"project_id": "test-project", "type": "service_account"}


def _make_ssm_client() -> SSMClient:
    """ダミーリージョン指定で SSM クライアントを生成する (Stubber 用)。"""
    return boto3.client("ssm", region_name="us-east-1")


def _param(name: str, value: str) -> dict[str, Any]:
    return {"Name": name, "Value": value, "Type": "SecureString"}


class TestLoadSecrets:
    def test_loads_all_secrets(self) -> None:
        client = _make_ssm_client()
        stubber = Stubber(client)
        stubber.add_response(
            "get_parameters",
            {
                "Parameters": [
                    _param(_PARAM_AZURE, "azure-key"),
                    _param(_PARAM_MAI_KEY, "mai-key"),
                    _param(_PARAM_MAI_ENDPOINT, "https://mai.example/"),
                    _param(_PARAM_VERTEX_SA, json.dumps(_FAKE_SA)),
                ],
            },
            {"Names": _ALL_PARAMS, "WithDecryption": True},
        )
        with stubber:
            secrets = load_secrets(client=client)

        assert secrets.azure_speech_key == "azure-key"
        assert secrets.mai_api_key == "mai-key"
        assert secrets.mai_endpoint == "https://mai.example/"
        assert secrets.vertex_sa_info == _FAKE_SA
        assert secrets.vertex_project == "test-project"

    def test_raises_on_invalid_parameters(self) -> None:
        client = _make_ssm_client()
        stubber = Stubber(client)
        stubber.add_response(
            "get_parameters",
            {
                "Parameters": [
                    _param(_PARAM_AZURE, "azure-key"),
                    _param(_PARAM_MAI_KEY, "mai-key"),
                    _param(_PARAM_VERTEX_SA, json.dumps(_FAKE_SA)),
                ],
                "InvalidParameters": [_PARAM_MAI_ENDPOINT],
            },
            {"Names": _ALL_PARAMS, "WithDecryption": True},
        )
        with stubber, pytest.raises(RuntimeError, match=_PARAM_MAI_ENDPOINT):
            load_secrets(client=client)

    def test_raises_on_invalid_vertex_json(self) -> None:
        client = _make_ssm_client()
        stubber = Stubber(client)
        stubber.add_response(
            "get_parameters",
            {
                "Parameters": [
                    _param(_PARAM_AZURE, "azure-key"),
                    _param(_PARAM_MAI_KEY, "mai-key"),
                    _param(_PARAM_MAI_ENDPOINT, "https://mai.example/"),
                    _param(_PARAM_VERTEX_SA, "not-json"),
                ],
            },
            {"Names": _ALL_PARAMS, "WithDecryption": True},
        )
        with stubber, pytest.raises(RuntimeError, match="Vertex SA JSON"):
            load_secrets(client=client)

    def test_raises_with_login_hint_on_sso_token_load_error(self) -> None:
        client = MagicMock()
        client.get_parameters.side_effect = SSOTokenLoadError(error_msg="expired")
        with pytest.raises(RuntimeError, match="aws sso login"):
            load_secrets(client=client)

    def test_raises_with_login_hint_on_unauthorized_sso_token(self) -> None:
        client = MagicMock()
        client.get_parameters.side_effect = UnauthorizedSSOTokenError()
        with pytest.raises(RuntimeError, match="aws sso login"):
            load_secrets(client=client)
