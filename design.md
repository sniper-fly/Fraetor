# Voice Input App - 要件定義 v5

## 概要

Linux 上で動作する音声入力アプリ。HTTP API で録音を開始/停止し、Azure STT でリアルタイム認識、認識結果をブラウザにリアルタイム表示する。録音停止後、LLM による自動校正を経てテキストを編集、クリップボードにコピーする。

## アーキテクチャ

```
HTTP API (POST /api/toggle-recording) <-- DE キーバインド (curl)
         |
         v
  Python常駐プロセス (FastAPI)
         |
         v
    Azure STT
    (認識)
         |
         v
SSE -> ブラウザ (TailwindCSS)
    |    |- メインタブ: 現在のセッション表示
    |    +- 履歴タブ: 過去セッション一覧
    |
録音停止後
    |
    v
POST /api/proofread (校正ON時)
    |    Vertex AI Gemini で自動校正
    |    (誤字脱字・句読点・フィラーワード修正)
    v
xclip でクリップボードにコピー
```

## 録音トグル

- `POST /api/toggle-recording` で録音開始/停止をトグル
- デスクトップ環境のキーバインド機能で任意のキーに `curl -X POST http://127.0.0.1:8765/api/toggle-recording` を割り当て
- Wayland / X11 どちらでもDEネイティブのキーバインドで動作

## 機能要件

| # | 要件 |
|---|------|
| 1 | Python 常駐プロセス (FastAPI) が HTTP API (`POST /api/toggle-recording`) で録音トグルを受け付け |
| 2 | トグル操作 → Azure STT Streaming 接続 → マイクキャプチャ開始 |
| 3 | Azure STT の interim → SSE でブラウザにリアルタイム表示（グレー） |
| 4 | Azure STT の recognized → そのまま確定テキストとして SSE でブラウザに表示（緑） |
| 5 | 再トグル → 録音停止、STT キューの残りイベントを処理 |
| 6 | 録音停止 → 校正ON時は LLM で自動校正 → textarea で確定テキストを編集 → クリップボードにコピー + JSONL に保存 |
| 7 | セッション終了後 → セッション結果を JSONL に保存 |
| 8 | **最大セッション時間: 3分**（定数で設定可能）。超過時は自動で録音停止 |
| 9 | ブラウザ GUI は通常タブとして開き、ユーザーが手動配置 |
| 10 | 履歴タブから個別セッションを削除可能 (`DELETE /api/history/{session_id}`) |
| 11 | 録音停止時に LLM (Vertex AI Gemini) でテキスト自動校正。デフォルトON、ブラウザUIでON/OFF切替可能 |
| 12 | 校正は誤字脱字・余計な句読点・フィラーワードを修正し、原文の意味を変えない |

## ブラウザ UI

### メインタブ (エディタモード)

```
┌─ Voice Input ──────────────────────────────────┐
│ [メイン] [履歴]                                   │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │          録音: ● 停止中  校正: [ON]              │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ <textarea> 確定テキスト (編集可能)              │ │
│ │                                                │ │
│ ├──────────────────────────────────────────────┤ │
│ │ それから...                          [認識中]  │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
└──────────────────────────────────────────────────┘
```

- `<textarea>` に確定済みテキストを蓄積。自由にカーソル移動・編集可能
- textarea の下に interim テキストを読み取り専用で表示
- SSE `recognized` イベント受信時: textarea 末尾にテキスト追加 (カーソル位置を保持)
- SSE `session_end` 受信時: 校正ON なら `POST /api/proofread` で校正後、`POST /api/finalize-session` で送信
- 新セッション開始時: textarea をクリア

### 履歴タブ

```
┌─ Voice Input ──────────────────────────────────┐
│ [メイン] [履歴]                                   │
│                                                  │
│ ┌─ 2026-04-04 14:32 ──────────────── [削除] ─┐  │
│ │ 明日の会議の資料を準備しておいてください。     │  │
│ │ よろしくお願いします。                        │  │
│ └────────────────────────────────────────────┘  │
│ ┌─ 2026-04-04 14:28 ──────────────── [削除] ─┐  │
│ │ 了解です                                     │  │
│ └────────────────────────────────────────────┘  │
│                                                  │
└──────────────────────────────────────────────────┘
```

- 履歴は JSONL ファイルから読み込み
- 新しいセッションが上に表示
- 各履歴カードの右上に「削除」ボタン。クリックで即削除（確認なし）
- 削除後は一覧を再取得して再描画

## セッション管理

| 項目 | 仕様 |
|------|------|
| セッション開始 | `POST /api/toggle-recording` → Azure STT 接続 → マイクキャプチャ開始 |
| セッション終了 | 再トグル、またはセッション時間上限 (3分) 到達 |
| ブラウザ表示 | セッション開始時にメインタブの表示をリセット |
| クリップボード | 当該セッションのテキストのみ |
| 履歴保存 | セッション終了時に JSONL に追記 |
| 履歴削除 | `DELETE /api/history/{session_id}` で個別削除 |

## データフロー

```
[録音中]
  マイク -> sounddevice(PCM) -> Azure STT Streaming
    -> recognizing -> SSE("interim", text)     -> ブラウザ (グレー表示)
    -> recognized  -> SSE("recognized", seg-N) -> ブラウザ (緑表示/確定)

[再トグル or 3分経過]
  録音停止 -> Azure STT切断
    -> STTキューの残イベントを処理
    -> session_end をブラウザに送信
    -> (校正ON時) ブラウザが POST /api/proofread でテキスト校正
       -> Vertex AI Gemini で校正 -> textarea 更新
    -> ブラウザが textarea の内容を POST /api/finalize-session で送信
    -> xclip にコピー
    -> JSONL に保存 (text フィールドは校正/編集済みテキスト)
```

## セグメント管理

```python
class Segment(BaseModel):
    id: int
    text: str            # Azure STT の認識結果

class Session(BaseModel):
    id: str              # UUID
    segments: list[Segment]
    started_at: datetime
    ended_at: datetime | None
    timed_out: bool      # セッション時間上限で終了したか
```

## 履歴保存 (JSONL)

ファイル: `~/.voice-input/history.jsonl`

```jsonl
{"id":"a1b2c3","started_at":"2026-04-04T14:28:00","ended_at":"2026-04-04T14:28:15","timed_out":false,"text":"了解です","segments":[{"text":"了解です"}]}
{"id":"d4e5f6","started_at":"2026-04-04T14:32:00","ended_at":"2026-04-04T14:32:30","timed_out":false,"text":"明日の会議の資料を準備しておいてください。よろしくお願いします。","segments":[{"text":"明日の会議の資料を準備しておいてください。"},{"text":"よろしくお願いします。"}]}
```

## 定数（設定可能）

```python
MAX_SESSION_DURATION_SEC = 180       # 最大セッション時間 (3分)
STABLE_PARTIAL_RESULT_THRESHOLD = 3  # Azure STT の StablePartialResultThreshold
                                     # partial result が安定とみなされるまでの閾値
                                     # 値が大きいほど interim の変動が少なく安定するが遅延が増す
AZURE_REGION = "japaneast"           # Azure Speech Services リージョン
AZURE_LANGUAGE = "ja-JP"             # 認識言語
STT_SAMPLE_RATE = 16000              # 音声サンプルレート

# --- 校正 ---
VERTEX_LOCATION = "global"               # Vertex AI エンドポイント (preview モデルはグローバルのみ)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"  # 校正用モデル
PROOFREAD_TIMEOUT_SEC = 15           # 校正 API タイムアウト
```

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| 録音トグル | HTTP API (`POST /api/toggle-recording`) + DE キーバインド |
| 音声キャプチャ | sounddevice |
| STT | Azure Speech Services (Streaming) |
| テキスト校正 | Vertex AI Gemini (google-genai SDK) |
| サーバー | FastAPI + SSE |
| フロントエンド | HTMX + SSE + TailwindCSS (CDN) |
| 履歴保存 | JSONL (`~/.voice-input/history.jsonl`) |
| クリップボード | xclip (X11) / wl-copy (Wayland) |

## 非機能要件

| 項目 | 仕様 |
|------|------|
| 対応環境 | Linux (X11 / Wayland) |
| 外部サービス | Azure Speech Services アカウント、Google Cloud Vertex AI |
| 認証情報管理 | AWS SSM Parameter Store (SecureString) を AWS SSO セッション経由で取得。SSM パラメータ名は環境変数 `FRAETOR_SSM_*` で指定。起動時に1回取得 |
| パッケージ管理 | uv (pyproject.toml + uv.lock) |
| 設定ファイル | 各種タイムアウト等は定数で管理 |

## 参考資料
https://learn.microsoft.com/ja-jp/python/api/azure-cognitiveservices-speech/azure.cognitiveservices.speech?view=azure-python
azure speech to text sdk は必要に応じてこちらの資料をWebFetchすること
azureの接続情報は azure_stt_key に記載してある
