# Voice Input App - 要件定義 v5

## 概要

Linux / macOS 上で動作する音声入力アプリ。HTTP API で録音を開始/停止し、MAI Transcribe でバッチ認識、認識結果をブラウザにリアルタイム表示する。録音停止後、LLM による自動校正を経てテキストを編集、クリップボードにコピーする。

## アーキテクチャ

```
HTTP API (POST /api/toggle-recording) <-- DE キーバインド (curl)
         |
         v
  Python常駐プロセス (FastAPI)
         |
         v
    MAI Transcribe
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
pyperclip でクリップボードにコピー
```

## 録音トグル

- `POST /api/toggle-recording` で録音開始/停止をトグル
- デスクトップ環境のキーバインド機能で任意のキーに `curl -X POST http://127.0.0.1:8765/api/toggle-recording` を割り当て
- Wayland / X11 どちらでもDEネイティブのキーバインドで動作

## 機能要件

| # | 要件 |
|---|------|
| 1 | Python 常駐プロセス (FastAPI) が HTTP API (`POST /api/toggle-recording`) で録音トグルを受け付け |
| 2 | トグル操作 → MAI Transcribe 接続 → マイクキャプチャ開始 |
| 3 | 録音停止時に MAI Transcribe でバッチ認識 → SSE でブラウザに表示 |
| 4 | MAI Transcribe の recognized → そのまま確定テキストとして SSE でブラウザに表示（緑） |
| 5 | 再トグル → 録音停止、STT キューの残りイベントを処理 |
| 6 | 録音停止 → 校正ON時は LLM で自動校正 → textarea で確定テキストを編集 → クリップボードにコピー + JSONL に保存 |
| 7 | セッション終了後 → セッション結果を JSONL に保存 |
| 8 | **最大セッション時間: 10分**（定数で設定可能）。超過時は自動で録音停止 |
| 9 | ブラウザ GUI は通常タブとして開き、ユーザーが手動配置 |
| 10 | 履歴タブから個別セッションを削除可能 (`DELETE /api/history/{session_id}`) |
| 11 | 録音停止時に LLM (Vertex AI Gemini) でテキスト自動校正。デフォルトON、ブラウザUIでON/OFF切替可能 |
| 12 | 校正は誤字脱字・余計な句読点・フィラーワードを修正し、原文の意味を変えない |
| 13 | 発話終了から2分間無音が続いたら自動で録音停止 (Silero VAD でローカル検出) |

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
| セッション開始 | `POST /api/toggle-recording` → MAI Transcribe 接続 → マイクキャプチャ開始 |
| セッション終了 | 再トグル、セッション時間上限 (10分) 到達、または発話終了から2分間の無音 |
| ブラウザ表示 | セッション開始時にメインタブの表示をリセット |
| クリップボード | 当該セッションのテキストのみ |
| 履歴保存 | セッション終了時に JSONL に追記 |
| 履歴削除 | `DELETE /api/history/{session_id}` で個別削除 |

## 音声キャプチャ (プラットフォーム別ライフサイクル戦略)

`AudioCapturePort` (`dictation/domain/ports.py`) がドメイン層のポートを定義し、
`SounddeviceCaptureBase` (`dictation/infrastructure/audio/sounddevice_base.py`)
が sounddevice 依存の共通実装 (PCM 取得: 16kHz/16-bit/mono、コールバック→
シンク書き込み) を提供する。ストリームのライフサイクル戦略だけを実装ごとに
分ける。`create_audio_capture()`
(`dictation/infrastructure/audio/factory.py`) がプラットフォームを判定して
実装を選択し、DIコンテナ (`containers.py`) が `AudioPipelineCoordinator` に
注入する。プラットフォーム分岐はファクトリの1箇所のみ。

| 実装 | 対象 | 戦略 |
|------|------|------|
| `PersistentStreamCapture` | macOS | ストリームを初回録音時に一度だけ開き、プロセス終了まで閉じない。録音 ON/OFF はシンク差し替えのみ |
| `PerSessionStreamCapture` | Linux (その他) | セッションごとにストリームを開閉し、録音中のみマイクを掴む |

- macOS で常駐方式を採る理由: PortAudio (CoreAudio バックエンド, v19.7.0 時点)
  には `stream.stop()/close()` が CoreAudio IO スレッドのリスナー発火と重なると
  ABBA デッドロックしてプロセス全体が固まる既知のバグがあるため、
  stop/close をそもそも呼ばない
- macOS のトレードオフ: 初回録音以降、マイクは常時オープン
  (マイク使用中インジケータが点灯し続ける)
- ストリームの open/stop/close はブロックし得る同期呼び出しのため、
  どの実装も `asyncio.to_thread` でイベントループから隔離する

## 発話区間検出 (VAD)

`SpeechActivityDetectorPort` (`dictation/domain/ports.py`) がポートを定義し、
`SileroSpeechActivityDetector`
(`dictation/infrastructure/vad/silero_vad_detector.py`) が Silero VAD を使い、
発話終了からの無音タイムアウトを検出する。`AudioPipelineCoordinator`
(`dictation/application/audio_pipeline_coordinator.py`) が `AudioCapturePort`
のシンクを STT (`feed_audio`) と VAD (`feed`) の両方に転送する composite sink
として組み立てる。

- Silero VAD は 512サンプル (16kHz時) 固定のウィンドウしか受け付けないため、
  `SpeechActivityDetector` 内部でバッファリングし、512サンプル単位に
  区切って推論する
- VAD推論はオーディオコールバックスレッド内で同期実行する。1ウィンドウ
  (32ms分) あたりの推論は1ms未満であり、既存の `feed_audio` と同程度に
  軽いため、別スレッド/非同期化は行わない
- VAD推論の例外はログに記録して握り潰し、録音・STTには伝播させない
- モデルは JIT 形式 (`load_silero_vad()` デフォルト、torch 経由) を使用。
  torch は CPU 専用ビルドを `pyproject.toml` の `[tool.uv.sources]` /
  `[[tool.uv.index]]` で固定し、GPU 関連の巨大な依存を回避している

## データフロー

```
[録音中]
  マイク -> sounddevice(PCM, 常駐ストリーム) -> MAI Transcribe (バッファリング)
                                             -> SpeechActivityDetector (Silero VAD)

[再トグル or 10分経過 or 発話終了から2分間無音]
  録音停止 -> MAI Transcribe バッチ認識
    -> recognized  -> SSE("recognized", seg-N) -> ブラウザ (緑表示/確定)
    -> session_end をブラウザに送信
    -> (校正ON時) ブラウザが POST /api/proofread でテキスト校正
       -> Vertex AI Gemini で校正 -> textarea 更新
    -> ブラウザが textarea の内容を POST /api/finalize-session で送信
    -> pyperclip にコピー
    -> JSONL に保存 (text フィールドは校正/編集済みテキスト)
```

## セグメント管理

録音中の実行時状態 (`RecordingSession`) と保存確定後のレコード
(`FinalizedSession`) はライフサイクル・不変条件が異なるため、別の集約として
モデル化する (詳細は「アーキテクチャ層構成」章参照)。

```python
# dictation/domain/models.py
class Segment(BaseModel):
    id: int
    text: str            # MAI Transcribe の認識結果

class RecordingSession(BaseModel):
    id: str              # UUID
    segments: list[Segment] = []
    started_at: datetime

# transcript_history/domain/models.py
class FinalizedSession(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    segments: list[Segment]
    started_at: datetime
    ended_at: datetime
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
MAX_SESSION_DURATION_SEC = 600       # 最大セッション時間 (10分)
SILENCE_TIMEOUT_SEC = 120            # 発話終了からの無音タイムアウト (2分)
STT_SAMPLE_RATE = 16000              # 音声サンプルレート

# --- VAD (Silero) ---
VAD_THRESHOLD = 0.5                  # 発話判定の閾値

# --- 校正 ---
VERTEX_LOCATION = "global"               # Vertex AI エンドポイント (preview モデルはグローバルのみ)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"  # 校正用モデル
PROOFREAD_TIMEOUT_SEC = 15           # 校正 API タイムアウト
```

## アーキテクチャ層構成

`src/` は Domain / Application / Infrastructure / Presentation の4層構成を
取る。境界づけられたコンテキストは単一で、内部を `dictation` (録音・認識・
タイムアウト) / `transcript_history` (確定履歴CRUD) / `proofreading` (校正)
の3モジュールに分割し、各モジュール内をレイヤー化する
(`shared/` は横断的インフラ、`presentation/` はHTTP層)。

```
dictation/
├── domain/            # RecordingSession, Segment, 各種ポート (ABC)
├── application/        # RecordingSessionService, AudioPipelineCoordinator,
│                        # SttEventRelay, SessionTimeoutMonitor
└── infrastructure/     # sounddevice実装, MaiTranscribeClient,
                         # SileroSpeechActivityDetector, SSEBroadcaster

transcript_history/
├── domain/            # FinalizedSession, HistoryRepositoryPort, ClipboardPort
├── application/        # FinalizeSessionUseCase
└── infrastructure/     # JsonlHistoryRepository, PyperclipClipboard

proofreading/
├── domain/            # ProofreadResult, ProofreadingPort
├── application/        # ProofreadTextUseCase
└── infrastructure/     # VertexGeminiProofreader

shared/                 # Settings, Secrets, ProcessShutdownerPort (横断的)
presentation/           # FastAPIルート・スキーマ (HTTP変換のみ)
```

依存方向: `Presentation → Application → Domain`、`Infrastructure → Domain`
(逆方向のimportは禁止)。Domain層はPydantic以外のサードパーティSDKに依存しない。
外部依存 (STT/Audio/Proofreading/履歴永続化/クリップボード/SSE配信/プロセス
制御) はすべて対応モジュールの `domain/ports.py` にポート (ABC) を定義し、
`infrastructure/` 配下が実装する。

DIコンテナ (`dependency-injector`) を `src/containers.py` の `Container` に
一元化する。FastAPIルートへの `@inject`/`Provide[]` wiring は mypy strict
との相性問題があるため使わず、`presentation/app.py` の lifespan 内で
Containerから取得したインスタンスを `app.state` に明示的に代入する。

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| 録音トグル | HTTP API (`POST /api/toggle-recording`) + DE キーバインド |
| 音声キャプチャ | sounddevice |
| 発話区間検出 | Silero VAD (ローカル/オフライン、CPU) |
| STT | MAI Transcribe (azure-ai-transcription SDK) |
| テキスト校正 | Vertex AI Gemini (google-genai SDK) |
| サーバー | FastAPI + SSE |
| フロントエンド | HTMX + SSE + TailwindCSS (CDN) |
| 履歴保存 | JSONL (`~/.voice-input/history.jsonl`) |
| クリップボード | pyperclip (Linux: xclip/wl-copy, macOS: pbcopy を自動選択) |
| DIコンテナ | dependency-injector |

## 非機能要件

| 項目 | 仕様 |
|------|------|
| 対応環境 | Linux (X11 / Wayland)、macOS (Apple Silicon) |
| 外部サービス | MAI Transcribe (Azure AI)、Google Cloud Vertex AI |
| 認証情報管理 | AWS SSM Parameter Store (SecureString) を AWS SSO セッション経由で取得。SSM パラメータ名は環境変数 `FRAETOR_SSM_*` で指定。起動時に1回取得 |
| パッケージ管理 | uv (pyproject.toml + uv.lock) |
| 設定ファイル | 各種タイムアウト等は定数で管理 |

## 将来課題

- 文字起こし中に次の録音を受け付けてキューイングする機能。現在は
  `SessionManager` が `asyncio.Lock` で `start_session`/`stop_session` を
  排他しており、`stop_session` 内の STT 完了待ちの間は次の録音を開始
  できない (待機はするが即座には始まらない)
