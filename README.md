# Fraetor

Linux 上で動作する音声入力アプリ。HTTP API で録音を開始/停止し、MAI Transcribe で音声認識、Gemini で自動校正、校正完了後に自動コピー

## セットアップ

### 依存関係

```bash
uv sync
```

### シークレット

AWS SSM Parameter Store (SecureString) に以下 3 つを作成し、 SSO 経由で取得します。

- MAI API キー
- MAI エンドポイント
- Vertex AI サービスアカウント JSON

`.env.example` を `.env` にコピーし、各 SSM パラメータパスを記入してください。

```bash
cp .env.example .env
$EDITOR .env
```

AWS への認証は SSO セッションを使います。

```bash
aws sso login --profile <your-profile>
export AWS_PROFILE=<your-profile>
export AWS_REGION=<your-region>
```

### 起動

```bash
uv run fraetor
```

## 使い方

- デスクトップ環境のキーバインドで任意のキーに録音トグルコマンドを割り当て
- ブラウザで `http://127.0.0.1:8765` を開くとリアルタイムで認識結果を確認可能
- 校正 ON/OFF はブラウザ UI 上のトグルで切り替え

### キーバインド設定

任意のキーに以下のコマンドを割り当ててください。サーバーが未起動の場合は自動で起動します:

```bash
/path/to/Fraetor/toggle-recording.sh
```

**GNOME**: 設定 → キーボード → キーボードショートカット → カスタムショートカット

**KDE**: システム設定 → ショートカット → カスタムショートカット

**Sway / Hyprland**: 設定ファイルに `bindsym` / `bind` を追加

## E2Eテスト

`tests/e2e/` 配下は通常の `uv run pytest` の探索対象から除外されている (`pyproject.toml` の `norecursedirs`)。リリース前にローカルで明示的に実行する低頻度の検証用で、実プロセス・実クラウド通信 (Azure MAI Transcribe / AWS SSM) を伴う。

### 前提

- 上記の「シークレット」「AWS への認証」セットアップが完了していること (SSO セッション必須)
- 音声フィクスチャ: `tests/e2e/fixtures/audio/README.md` の手順に従って各開発者が録音して配置する (実際の声を含むためコミット対象外)
- Playwright の Chromium ブラウザバイナリと OS 依存ライブラリ:
  ```bash
  uv run playwright install --with-deps chromium
  ```
  `--with-deps` は `apt` 経由で共有ライブラリをインストールするため `sudo` 権限が必要。バイナリのみで良い場合は `uv run playwright install chromium` (sudo不要)。

### 実行

```bash
uv run pytest tests/e2e --ignore=tests/e2e/test_browser_ui.py
uv run pytest tests/e2e/test_browser_ui.py
```

AWS プロファイルは環境変数で明示指定する。シェルに別プロファイルが設定されて
いると `.env` の値では上書きされず (`load_dotenv` の既定は `override=False`)、
SSM の `GetParameters` が `AccessDeniedException` になってサーバーが起動できず、
クラウド通信を伴うテストがまとめて失敗する。

```bash
AWS_PROFILE=<プロファイル名> uv run pytest tests/e2e --ignore=tests/e2e/test_browser_ui.py
```

### 既知のプラットフォーム制約

`TestAudioDeviceFailure::test_missing_audio_device_broadcasts_error` は
**Linux 専用**。壊れたデバイスの再現に `ALSA_CONFIG_PATH` を使うため、
macOS (CoreAudio) ではこの環境変数が無視されてマイクが正常に開き、期待する
`error` イベントが発生せず必ず失敗する。macOS ではこの1件の失敗は既知として
扱う。

