# Fraetor

Linux (X11) 上で動作する音声入力アプリ。ホットキーで録音を開始/停止し、Azure STT でリアルタイム認識、Gemini Live API で自動校正、校正完了後にアクティブウィンドウへ自動ペーストする。

## セットアップ

### 依存関係

```bash
uv sync
```

### シークレット

`pass` コマンドに以下のエントリが必要:

- `api/azure_stt_key` — Azure Speech Services キー
- `api/gemini` — Google AI (Gemini) API キー

### systemd サービス登録（必須）

evdev でホットキーを監視するために `/dev/input/event*` への読み取り権限が必要です。`input` グループにユーザーを追加する代わりに、systemd サービスとして実行することでプロセスレベルで権限を分離します。

詳細な手順は [docs/systemd-setup.md](docs/systemd-setup.md) を参照してください。

```bash
# サービス起動（ログイン後に手動で実行）
sudo systemctl start fraetor

# 状態確認
sudo systemctl status fraetor

# ログ確認
journalctl -u fraetor -f
```

> **注意**: `pass` コマンドによるGPG復号が必要なため、自動起動 (`systemctl enable`) は使用できません。ログイン後に手動で起動してください。

## 使い方

- **F9**: 録音開始/停止トグル
- ブラウザで `http://127.0.0.1:8765` を開くとリアルタイムで認識結果を確認可能
- 校正 ON/OFF はブラウザ UI 上のトグルで切り替え
