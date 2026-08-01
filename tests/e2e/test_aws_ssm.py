"""AWS SSM Parameter Store 経由の認証を検証するE2Eテスト。

正常系は `.env` の実SSMパラメータパスを使い、実際にAWS SSOセッション
経由で値が取れることを検証する。異常系は `moto` でSSM応答を模擬し、
シークレット取得コード自体は変えずにAWS応答だけを差し替える。
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from src.config import init_secrets, validate_api_keys
from src.secrets_loader import load_secrets


class TestRealAwsSso:
    def test_init_secrets_succeeds_via_real_sso_session(self) -> None:
        """正常系: 実AWS SSOセッション経由でシークレットが取得でき、警告が出ない"""
        init_secrets()

        warnings = validate_api_keys()

        assert warnings == []


class TestInvalidParameters:
    def test_missing_parameter_raises_invalid_parameters_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """異常系: 一部パラメータ未存在でInvalidParametersエラーになる"""
        monkeypatch.setenv("FRAETOR_SSM_MAI_API_KEY", "/fraetor-e2e/mai_api_key")
        monkeypatch.setenv("FRAETOR_SSM_MAI_ENDPOINT", "/fraetor-e2e/mai_endpoint")
        monkeypatch.setenv("FRAETOR_SSM_VERTEX_SA", "/fraetor-e2e/vertex_sa_missing")

        with mock_aws():
            client = boto3.client("ssm", region_name="us-east-1")
            client.put_parameter(
                Name="/fraetor-e2e/mai_api_key", Value="key", Type="SecureString"
            )
            client.put_parameter(
                Name="/fraetor-e2e/mai_endpoint",
                Value="https://mai.example/",
                Type="SecureString",
            )

            with pytest.raises(RuntimeError, match="vertex_sa_missing"):
                load_secrets(client=client)
