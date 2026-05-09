# Fraetor

Linux 上で動作する音声入力アプリ。HTTP API で録音を開始/停止し、Azure STT でリアルタイム認識、Gemini Live API で自動校正、校正完了後に自動コピー

## セットアップ

### 依存関係

```bash
uv sync
```

### シークレット

AWS SSM Parameter Store (SecureString) に以下 4 つを作成し、 SSO 経由で取得します。

- Azure Speech Services キー
- Azure MAI API キー
- Azure MAI エンドポイント
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
