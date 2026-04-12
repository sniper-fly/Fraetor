# Fraetor Lite - Azure STT 単体構成 要件定義・仕様書

## 1. Azure STT リアルタイム文字起こしの仕組み

現行の Fraetor では、Azure Speech Services の **Continuous Recognition (連続認識)** を利用してリアルタイム文字起こしを実現している。以下にその仕組みを解説する。

### 1.1 音声入力からAzure STTへの流れ

```
マイク
  │  sounddevice (InputStream, 16kHz/16bit/mono)
  │  コールバックで PCM バイト列を取得
  ▼
PushAudioInputStream
  │  Azure SDK が提供するプッシュ型ストリーム
  │  アプリ側が write() で PCM データを書き込む
  ▼
SpeechRecognizer (continuous recognition)
  │  バックグラウンドスレッドで音声を解析
  │  発話区間を自動検出し、認識結果をイベントで通知
  ▼
イベントハンドラ (recognizing / recognized)
```

### 1.2 PushAudioInputStream (プッシュ型ストリーム)

Azure SDK には Pull 型と Push 型の 2 つの音声入力方式がある。本プロジェクトでは **Push 型** を採用している。

- アプリケーション側が任意のタイミングで `write(buffer)` を呼び、PCM バイト列を Azure SDK に渡す
- sounddevice のコールバック (`_audio_callback`) が呼ばれるたびに `indata.tobytes()` を `push_stream.write()` へ転送する
- 録音終了時に `push_stream.close()` を呼ぶと、Azure SDK は残りのバッファを処理して認識を完了する

### 1.3 2 種類の認識イベント

Azure の連続認識は 2 種類のイベントを発火する。

#### recognizing (中間結果 / interim)

- 発話中にリアルタイムで発火する
- 同一発話内でテキストが次第に長くなり、修正されながら更新される
- 例: `"今日は"` → `"今日は天気が"` → `"今日は天気がいいので"`
- **不確定** であり、次の `recognizing` イベントで上書きされる
- UI ではグレー表示で「認識中」を示す

#### recognized (確定結果)

- Azure が発話の区切り（ポーズ、文末）を検出したときに発火する
- **確定済み** のテキストで、以後変更されない
- 1 回の `recognized` が 1 セグメントに対応する
- UI では緑色で確定表示する

### 1.4 StablePartialResultThreshold

`recognizing` イベントの安定度を制御するパラメータ。

- 値が大きいほど中間結果の変動が抑えられ安定するが、表示遅延が増す
- 値が小さいほどリアルタイム性が高いが、テキストの変動が激しい
- 現行値: `3`

### 1.5 スレッドモデルとイベントキュー

Azure SDK のイベントハンドラはバックグラウンドスレッドから呼ばれる。FastAPI (asyncio) のイベントループとは別スレッドのため、`loop.call_soon_threadsafe()` を使って `asyncio.Queue` に安全にイベントを投入する。

```
[Azure SDK スレッド]                     [asyncio イベントループ]
  recognizing →                           
    loop.call_soon_threadsafe(             stt_event_queue.get()
      queue.put_nowait,        ────→        ↓
      {"type":"interim",...})              SSE broadcast → ブラウザ
                                          
  recognized →                            
    loop.call_soon_threadsafe(             stt_event_queue.get()
      queue.put_nowait,        ────→        ↓
      {"type":"recognized",...})           セグメント確定 → SSE broadcast
```

### 1.6 セグメントの形成

1 回の `recognized` イベントが 1 つのセグメントになる。セッション中に複数の文を話すと、文ごとにセグメントが生成される。

```
発話: "今日は天気がいいので散歩に行こうと思います。あと買い物にも行かないと。"

  recognized(1): "今日は天気がいいので散歩に行こうと思います。"  → セグメント 0
  recognized(2): "あと買い物にも行かないと。"                   → セグメント 1
```

---

## 2. 概要

Linux 上で動作する音声入力アプリ。HTTP API で録音を開始/停止し、Azure STT でリアルタイム文字起こしを行い、ブラウザ UI にリアルタイム表示する。録音停止後、テキストを編集してクリップボードにコピーする。

現行版との主な違い:

- **Gemini Live API による校正を廃止** — Azure STT の認識結果をそのまま確定テキストとして使用する
- 校正関連の機能（校正 ON/OFF トグル、校正キュー、校正タイムアウト、校正プロンプト）を全て除去
- データモデルとセッション管理を簡素化

## 3. アーキテクチャ

```
HTTP API (POST /api/toggle-recording) ←── DE キーバインド (curl)
         │
         ▼
  Python常駐プロセス (FastAPI)
         │
    ┌────┴────┐
    ▼         │
Azure STT     │
(認識)         │
    │         │
    ▼         │
SSE → ブラウザ (TailwindCSS)
    │    ├─ メインタブ: 現在のセッション表示
    │    └─ 履歴タブ: 過去セッション一覧
    │
録音停止後
    ▼
xclip でクリップボードにコピー
```

## 4. 機能要件

| #  | 要件 |
|----|------|
| 1  | Python 常駐プロセス (FastAPI) が HTTP API (`POST /api/toggle-recording`) で録音トグルを受け付け |
| 2  | トグル操作 → Azure STT Streaming 接続 → マイクキャプチャ開始 |
| 3  | Azure STT の interim → SSE でブラウザにリアルタイム表示（グレー） |
| 4  | Azure STT の recognized → そのまま確定テキストとして SSE でブラウザに表示（緑） |
| 5  | 再トグル → 録音停止、STT キューの残りイベントを処理 |
| 6  | 録音停止 → textarea で確定テキストを編集 → クリップボードにコピー + JSONL に保存 |
| 7  | セッション終了後 → セッション結果を JSONL に保存 |
| 8  | **最大セッション時間: 3分**（定数で設定可能）。超過時は自動で録音停止 |
| 9  | ブラウザ GUI は通常タブとして開き、ユーザーが手動配置 |

## 5. データフロー

```
[録音中]
  マイク → sounddevice(PCM 16kHz/16bit/mono) → Azure STT Streaming
    → recognizing → SSE("interim", text)     → ブラウザ (グレー表示)
    → recognized  → SSE("recognized", seg-N) → ブラウザ (緑表示/確定)

[再トグル or 3分経過]
  録音停止 → Azure STT 切断
    → STTキューの残イベントを処理
    → session_end をブラウザに送信
    → ブラウザが textarea の内容を POST /api/finalize-session で送信
    → xclip にコピー
    → JSONL に保存 (text フィールドは編集済みテキスト)
```

## 6. データモデル

```python
from pydantic import BaseModel

class Segment(BaseModel):
    id: int
    text: str          # Azure STT の認識結果 (recognized)

class Session(BaseModel):
    id: str            # UUID
    segments: list[Segment]
    started_at: datetime
    ended_at: datetime | None = None
    timed_out: bool = False

    @property
    def full_text(self) -> str:
        return "".join(seg.text for seg in self.segments if seg.text)
```

現行版との差分:

- `Segment`: `status`, `raw_text`, `corrected_text` の 3 フィールドを `text` 1 フィールドに統合。校正がないため `interim` / `correcting` / `corrected` のステータス遷移は不要
- `Session`: `correction_enabled` フィールドを削除

## 7. API 仕様

### エンドポイント一覧

| メソッド | パス | 用途 |
|---------|------|------|
| GET | `/` | index.html を返す |
| GET | `/events` | SSE ストリーム |
| POST | `/api/toggle-recording` | 録音開始/停止トグル |
| GET | `/api/history` | 履歴一覧を取得 |
| POST | `/api/finalize-session` | 編集済みテキストの最終送信 |

現行版から削除されるエンドポイント:

- `POST /api/correction-toggle`
- `GET /api/correction-status`

### SSE イベント一覧

| イベント名 | データ | 用途 |
|-----------|--------|------|
| `interim` | `{"text": "..."}` | 中間結果の表示（グレー） |
| `recognized` | `{"segment_id": N, "text": "..."}` | 確定テキストの表示（緑） |
| `status` | `{"recording": true/false}` | 録音状態の通知 |
| `session_end` | `{}` | セッション終了通知 |
| `keepalive` | `""` | 接続維持 |
| `error` | `{"message": "..."}` | エラー通知 |

現行版との差分:

- `corrected` イベントを `recognized` に名称変更（校正処理を経ないため、より実態に即した名前にする）

### POST /api/toggle-recording

- レスポンス: `{"recording": bool}`
- 録音中でなければ開始、録音中なら停止

### POST /api/finalize-session

- リクエストボディ: `{"text": "編集済みテキスト"}`
- レスポンス: `{"ok": bool}`
- ブラウザから編集済みテキストを受け取りクリップボードにコピー

### GET /api/history

- レスポンス: `[{"id": "...", "started_at": "...", ...}, ...]`
- 新しいセッションが先頭

## 8. ブラウザ UI

### メインタブ (エディタモード)

```
┌─ Voice Input ──────────────────────────────────┐
│ [メイン] [履歴]                                   │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │                    録音: ● 停止中               │ │
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
- SSE `recognized` イベント受信時: textarea 末尾にテキスト追加（カーソル位置を保持）
- SSE `session_end` 受信時: textarea の内容を `POST /api/finalize-session` で送信
- 新セッション開始時: textarea をクリア

### 履歴タブ

```
┌─ Voice Input ──────────────────────────────────┐
│ [メイン] [履歴]                                   │
│                                                  │
│ ┌─ 2026-04-04 14:32 ─────────────────────────┐  │
│ │ 明日の会議の資料を準備しておいてください。     │  │
│ │ よろしくお願いします。                        │  │
│ └────────────────────────────────────────────┘  │
│ ┌─ 2026-04-04 14:28 ─────────────────────────┐  │
│ │ 了解です                                     │  │
│ └────────────────────────────────────────────┘  │
│                                                  │
└──────────────────────────────────────────────────┘
```

- 現行版から `(校正ON)` / `(校正OFF)` の表記を削除

## 9. セッション管理

| 項目 | 仕様 |
|------|------|
| セッション開始 | `POST /api/toggle-recording` → Azure STT 接続 → マイクキャプチャ開始 |
| セッション終了 | 再トグル、またはセッション時間上限 (3分) 到達 |
| ブラウザ表示 | セッション開始時にメインタブの表示をリセット |
| クリップボード | 当該セッションのテキストのみ |
| 履歴保存 | セッション終了時に JSONL に追記 |

### セッションライフサイクル

```
[開始]
  POST /api/toggle-recording (recording=false → true)
    1. Session オブジェクト生成
    2. AzureSttClient 生成・開始 (continuous recognition)
    3. AudioCapture 生成・開始 (sounddevice InputStream)
    4. STT イベント処理タスク開始
    5. セッションタイムアウトタスク開始
    6. SSE broadcast: status {recording: true}

[録音中]
  AudioCapture._audio_callback
    → stt_client.write_audio(PCM bytes)
    → Azure SDK が認識処理
    → recognizing / recognized イベント
    → stt_event_queue に投入
    → _process_stt_events が消費
    → SSE broadcast: interim / recognized

[停止]
  POST /api/toggle-recording (recording=true → false)
    1. AudioCapture 停止
    2. AzureSttClient 停止 (push_stream.close → stop_continuous_recognition)
    3. STT イベント処理タスクをキャンセル
    4. STT キューの残イベントを処理 (_drain_stt_queue)
    5. pending_session 設定
    6. SSE broadcast: session_end, status {recording: false}
```

### エラー時の振る舞い

| 障害箇所 | 振る舞い |
|---------|---------|
| Azure STT 接続失敗 | セッション開始を中断、error イベントをブラウザに送信 |
| Audio デバイス取得失敗 | セッション開始を中断、error イベントをブラウザに送信 |
| Azure STT 認識中キャンセル | ログ出力のみ（SDK が内部処理） |
| クリップボード/ペースト失敗 | ログ出力、セッション自体は正常終了 |

## 10. 履歴保存 (JSONL)

ファイル: `~/.voice-input/history.jsonl`

```jsonl
{"id":"a1b2c3","started_at":"2026-04-04T14:28:00","ended_at":"2026-04-04T14:28:15","timed_out":false,"text":"了解です","segments":[{"text":"了解です"}]}
{"id":"d4e5f6","started_at":"2026-04-04T14:32:00","ended_at":"2026-04-04T14:32:30","timed_out":false,"text":"明日の会議の資料を準備しておいてください。よろしくお願いします。","segments":[{"text":"明日の会議の資料を準備しておいてください。"},{"text":"よろしくお願いします。"}]}
```

現行版との差分:

- `correction_enabled` フィールド削除
- `segments` 内の `raw_text` / `corrected_text` を `text` に統合

## 11. 定数 (設定可能)

```python
MAX_SESSION_DURATION_SEC = 180       # 最大セッション時間 (3分)
STABLE_PARTIAL_RESULT_THRESHOLD = 3  # Azure STT の StablePartialResultThreshold
AZURE_REGION = "japaneast"           # Azure Speech Services リージョン
AZURE_LANGUAGE = "ja-JP"             # 認識言語
STT_SAMPLE_RATE = 16000              # 音声サンプルレート (Hz)
SERVER_HOST = "127.0.0.1"            # サーバーリッスンアドレス
SERVER_PORT = 8765                   # サーバーリッスンポート
SSE_KEEPALIVE_SEC = 15               # SSE キープアライブ間隔 (秒)
```

現行版から削除される定数:

- `CORRECTION_TIMEOUT_SEC`
- `GEMINI_MODEL`
- `CORRECTION_PROMPT`
- `GEMINI_API_KEY`

## 12. モジュール構成

```
src/
├── __main__.py          # エントリポイント (uv run fraetor)
├── __init__.py
├── app.py               # FastAPI アプリ + lifespan
├── config.py            # 定数 + シークレット読み込み
├── models.py            # Segment, Session (Pydantic)
├── state.py             # AppState (キュー, ブロードキャスタ, 状態)
├── routes.py            # HTTP エンドポイント
├── session_manager.py   # SessionManager (ライフサイクル管理)
├── stt.py               # AzureSttClient (Azure SDK ラッパー)
├── audio.py             # AudioCapture (sounddevice ラッパー)
├── sse.py               # SSEBroadcaster (多クライアント配信)
├── clipboard.py         # xclip / xdotool ラッパー
├── history.py           # JSONL 永続化
├── logging_config.py    # 構造化ログ設定
└── templates/
    └── index.html       # フロントエンド (HTMX + SSE + TailwindCSS)
```

現行版から削除されるモジュール:

- `correction.py` (GeminiCorrectionClient)

### AppState の簡素化

```python
class AppState:
    stt_event_queue: asyncio.Queue[dict[str, str]]  # STT イベントキュー
    broadcaster: SSEBroadcaster                      # SSE 配信
    current_session: Session | None                  # 現在のセッション
    recording: bool                                  # 録音状態
    pending_session: Session | None                  # finalize 待ちの保留セッション
```

現行版から削除されるフィールド:

- `correction_queue` (校正キュー)
- `correction_enabled` (校正 ON/OFF)

## 13. 技術スタック

| レイヤー | 技術 |
|---------|------|
| 録音トグル | HTTP API (`POST /api/toggle-recording`) + DE キーバインド |
| 音声キャプチャ | sounddevice |
| STT | Azure Speech Services (Streaming / Continuous Recognition) |
| サーバー | FastAPI + SSE (sse-starlette) |
| フロントエンド | HTMX + SSE + TailwindCSS (CDN) |
| 履歴保存 | JSONL (`~/.voice-input/history.jsonl`) |
| クリップボード | xclip |
| データバリデーション | Pydantic |
| パッケージ管理 | uv |

現行版から削除される依存:

- `google-genai` (Gemini Live API)

## 14. 非機能要件

| 項目 | 仕様 |
|------|------|
| 対応環境 | Linux (X11 / Wayland) |
| 外部サービス | Azure Speech Services アカウント |
| 認証情報管理 | `pass` コマンド (エントリ: `api/azure_stt_key`)。起動時に 1 回取得 |
| パッケージ管理 | uv (pyproject.toml + uv.lock) |
| 設定ファイル | 各種タイムアウト等は定数で管理 |
| ログ | 構造化 JSON ログ |

## 15. 参考資料

- Azure Speech SDK for Python: https://learn.microsoft.com/ja-jp/python/api/azure-cognitiveservices-speech/azure.cognitiveservices.speech
- Azure STT 接続情報: `azure_stt_key` ファイル
