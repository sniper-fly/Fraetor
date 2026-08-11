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
| 14 | 無音が3秒続いたら、そこまでの発話区間を1セグメントとして逐次文字起こしに送る (録音中にテキストが順次確定していく) |
| 15 | 一部の設定値はプロセス再起動なしにブラウザの設定タブから変更できる (「動的設定」章参照) |

## ブラウザ UI

### メインタブ (エディタモード)

```
┌─ Voice Input ──────────────────────────────────┐
│ [メイン] [履歴] [設定]                             │
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

- `<textarea>` には常に「表示キュー先頭 (`sessionQueue[0]`) のセッション」の
  確定済みテキストのみを表示する。自由にカーソル移動・編集可能
- textarea の下に interim テキストを読み取り専用で表示 (先頭セッションの分のみ)
- SSE `recognized` イベント受信時: `session_id` が指す表示キュー内セッションに
  テキストを蓄積。先頭セッションの場合のみ textarea 末尾に追加表示
  (カーソル位置を保持)。1セッションの録音中に無音区切りごとに複数回届く
  (「逐次文字起こし (無音区切り)」章参照)
- SSE `session_end` 受信時: 該当セッションを完了済みにする。先頭セッションが
  完了していれば、校正ON時は `POST /api/proofread` で校正後、
  `POST /api/finalize-session` で送信し確定する。**textarea はこの時点では
  クリアしない**。確定済みのテキストは、次のセッションの録音が開始され
  表示が切り替わるまでそのまま表示され続ける (詳細は「セッション管理」章参照)
- SSE `status(recording=true)` 受信時: 新セッションが表示キュー先頭なら、
  ここで初めて textarea をクリアして表示を切り替える

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

### 設定タブ

```
┌─ Voice Input ──────────────────────────────────┐
│ [メイン] [履歴] [設定]                             │
│                                                  │
│ ┌────────────────────────────────────────────┐  │
│ │ 最大セッション時間            [   600 ] 秒  │  │
│ │ 無音セッション終了            [   120 ] 秒  │  │
│ │ 無音区切り (逐次文字起こし)   [   3.0 ] 秒  │  │
│ │ 発話判定の閾値                [   0.5 ] 0〜1│  │
│ │ ...                                          │  │
│ └────────────────────────────────────────────┘  │
│ [保存]  保存しました (次回の録音から反映されます)   │
└──────────────────────────────────────────────────┘
```

- タブ表示時に `GET /api/settings` で現在値を読み、入力欄を生成する
- 入力欄の一覧はJS側の `SETTINGS_FIELDS` (項目名・ラベル・単位・step) が
  唯一の定義元。`DynamicSettings` との項目一致は
  `tests/presentation/routes/test_page_routes.py` で検証する
  (片方だけ増減すると、欠落項目が既定値へ静かに戻るため)
- 「保存」で全項目を `PUT /api/settings` に送る。部分更新ではない
- 422 のバリデーションエラーは FastAPI の `detail` を整形してその場に表示する

## セッション管理

| 項目 | 仕様 |
|------|------|
| セッション開始 | `POST /api/toggle-recording` → MAI Transcribe 接続 → マイクキャプチャ開始。SSE `status(recording=true, session_id)` でブラウザの表示キューにセッションを登録し、新セッションが表示キュー先頭ならここで初めて textarea をクリアして表示を切り替える |
| セッション終了 (録音停止) | 再トグル、セッション時間上限 (10分) 到達、または発話終了から2分間の無音。`RecordingSessionService.stop_session()` は文字起こし本体 (STT の `stop()`) を待たずに即座に返る |
| 文字起こし処理 | 録音停止と非同期に `TranscriptionQueue` がFIFOで直列処理する (詳細は「文字起こしキュー」章参照)。処理中でも次のセッションをすぐに開始できる |
| ブラウザ表示 (セッション分離) | すべてのSSEイベントに `session_id` が乗る。ブラウザは `session_id` ごとに独立したテキストを蓄積する表示キュー (`sessionQueue`) を持ち、textareaには常にキュー先頭セッションの内容のみを表示する。他セッションの `recognized` 結果はtextareaに一切反映されない (詳細は「文字起こしキュー」章参照) |
| 自動確定フロー | 表示キュー先頭のセッションが `session_end` を受信すると、校正ON時は校正後に `POST /api/finalize-session` (session_id指定) で確定 → 表示キューから除去 → 次のセッションが既に完了済みなら即座に連続して確定する。**textareaは確定直後にはクリアしない**。確定済みのテキストは、次のセッションの録音が開始され表示が切り替わるまでそのまま表示され続ける (即座にクリアすると確定済みテキストが一瞬しか見えずに消えてしまうため)。複数セッションが同時に完了待ちでも、**完了順に1件ずつ自動確定**され、ユーザーの手動操作は不要 |
| クリップボード | 直近に確定したセッションのテキストのみがコピーされる (他セッションの内容と混在しない) |
| 履歴保存 | 文字起こし完了時ではなく、確定 (`finalize-session`) 時に JSONL に追記。各エントリは対応する1セッションの内容のみを含み、他セッションと混在しない |
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
- 無音タイムアウト用の `last_speech_time` (`time.monotonic()` 基準) に加え、
  逐次文字起こしの前方無音削除用に `last_speech_start_sample` を公開する。
  `VADIterator` が発話開始時に返す `start` (= `speech_pad_ms` 分さかのぼった
  累積サンプル位置) をそのまま保持する。基準はこのVADインスタンスに投入した
  累積サンプル数で、STTへ渡すPCMと同一ストリームなので、`* 2` (16bit) で
  そのままバッファのバイトオフセットに換算できる。発話未検出時は `None`
- モデルは JIT 形式 (`load_silero_vad()` デフォルト、torch 経由) を使用。
  torch は CPU 専用ビルドを `pyproject.toml` の `[tool.uv.sources]` /
  `[[tool.uv.index]]` で固定し、GPU 関連の巨大な依存を回避している

## 逐次文字起こし (無音区切り)

録音中に無音が `segment_silence_sec` 秒 (既定3秒) 続いた時点で、そこまでの
発話区間を1セグメントとして送信する。セッション全体を停止時に1回送る方式に
比べ、確定までのリードタイムがセッション長に比例して伸びなくなり、無音区間を
送らない分だけデータ量も減る。トレードオフとしてAPIリクエスト回数は増える。

- **`SegmentSilenceMonitor`** (`dictation/application/`):
  `SessionTimeoutMonitor` と同じ「残り時間だけ `asyncio.sleep` して起きる」
  方式。ただし1セッション中に何度も発火するため、発火後もループを続ける。
  無音が続く間は `segment_silence_sec` おきに発火し続けるが、「送るものが
  あるか」の判定は送信済み位置を知っているSTTクライアント側のno-opガードに
  委ねる (監視側が状態を二重に持たない)
- **`SttEnginePort.flush(trim_before_sample)`**: 未送信区間のうち
  `trim_before_sample` 以降を1セグメントとして送信する。`stop()` と同じく
  `recognized` イベントをキューに投入する。失敗しても例外は伝播させず、
  そのセグメントのテキストを失うだけに留める (リトライなし。録音は継続する)
- **`MaiTranscribeClient` のバッファ方式**: セッション全体の生PCMを
  `_buffer` に保持し続け、どこまで送ったかを `_sent_offset_bytes` で覚える。
  送信済みの分を捨てないのは、無音区切りの直前で語頭が欠けた場合に前の区間へ
  さかのぼって切り出せる余地を残すため。バッファは `stop()`/`start()` で
  解放され、1セッション上限 (10分/16kHz/16bit/mono ≒ 19MB) を超えない。
  `threading.Lock` はメモリ操作 (追記・切り出し・オフセット更新) のみを
  保護し、WAV化・HTTP送信はロックの外で行う (`feed_audio` は sounddevice の
  コールバックスレッド、`flush`/`stop` はイベントループから呼ばれる)
- **前方無音の削除**: VAD の `last_speech_start_sample` を
  `trim_before_sample` として渡す。発話が既に送信済みの区間で始まっていた
  場合は再送しないよう送信済み位置を優先する (`max()` を取る)
- **flush の直列化**: `AudioPipelineCoordinator` が `asyncio.Lock` で
  flush 全体を囲む。並走するとレスポンス順の揺れで `SegmentAccumulator` が
  到着順に振るセグメントIDの順序が崩れるため。`TranscriptionQueue` が
  単一ワーカーでセッション間の順序を守るのと同じ考え方をセッション内に
  適用している
- **`stop()` は進行中の flush を待つ**: 監視タスクを止める前に
  `_flush_lock` を取得する。送信中にキャンセルすると、送信済みオフセットだけ
  が進んでその区間のテキストが失われる (`stop()` の最終送信も拾えない)。
  待ち時間は flush 自身の `mai_timeout_sec` で上限が付く

`SegmentAccumulator`/SSE/フロントエンドは変更していない。`recognized` を
複数回受け取って逐次追記する経路は元から成立しており、flush 由来のイベントも
同じ経路を通る。

## 動的設定 (DynamicSettings)

設定値は反映タイミングの違いで2種類に分かれる。

| | `Settings` | `DynamicSettings` |
|---|---|---|
| 構築 | 起動時に環境変数から1回 (`frozen`) | 起動時にJSONCから読み、実行中に差し替え可 (`frozen`) |
| 変更手段 | 環境変数 + プロセス再起動 | ブラウザの設定タブ (`PUT /api/settings`) |
| 反映 | 再起動時 | 次回利用時 (セッション開始時/校正実行時/SSE接続時/shutdown時) |

`src/shared/config/` に配置する (どの業務コンテキストにも属さない横断的関心事)。
`ports.py` の `SettingsRepositoryPort` (`get`/`update`) をポートとし、
`JsoncSettingsRepository` が `~/.voice-input/settings.jsonc` へ永続化する。

- 現在値はメモリ上に保持し、`get()` はファイルI/Oを伴わない
- ファイル不在時は各項目の説明コメント付きの雛形を書き出す。パース失敗・
  バリデーション違反時は警告ログを出して既定値へフォールバックする
  (`_load_secrets_or_empty` と同じ「起動を止めない」方針)
- `update()` はファイル全体を書き直すため、ユーザーが書いたコメントは失われる
  (設定画面経由の更新なので許容する)
- クロスフィールド制約: `segment_silence_sec < silence_timeout_sec`。逆転すると
  セグメントが1度も切り出されないままセッションがタイムアウトする

**動的化の対象**: `max_session_duration_sec` / `silence_timeout_sec` /
`segment_silence_sec` / `vad_threshold` / `mai_locale` / `mai_model_name` /
`mai_timeout_sec` / `proofread_timeout_sec` / `shutdown_delay_sec` /
`sse_keepalive_sec`

**`Settings` に残すもの (動的化しない)**: `stt_sample_rate` (Singletonの
`audio_capture` に紐づき、マイクストリーム再起動が必要)、`proofread_prompt` /
`gemini_model` (校正クライアントのSingleton生成に紐づく)、`vertex_location`
(認証クライアントの再構築が必要)、`server_host` / `server_port` (TCP bindは
プロセス起動時に確定し原理的に変更不可)、`history_dir` (実行中の切り替えは
データ配置の整合性リスクが高い)。

**「次回利用時に反映」の実現方法**: 消費側は値をコピーして保持せず、利用する
瞬間に `settings_repository.get()` を呼ぶ。`vad_factory`/`stt_engine_factory`
はファクトリ関数が `settings_repository` を受け取り、生成時に `get()` を読む。
Singleton の `AudioPipelineCoordinator` には値ではなく
`segment_silence_sec_fn` (callable) を渡し、セッション開始時に評価する
(値を直接束縛すると起動時の値に固定される)。

## データフロー

録音の開始/停止 (レーン1) と文字起こし処理 (レーン2) は非同期に進行する。
レーン1が即座に完了することで、レーン2がまだ処理中でも次の録音を
すぐに開始できる (「文字起こしキュー」章参照)。

```
[レーン1: 録音中 (RecordingSessionService / AudioPipelineCoordinator)]
  マイク -> sounddevice(PCM, 常駐ストリーム) -> MAI Transcribe (バッファリング)
                                             -> SpeechActivityDetector (Silero VAD)

[録音中: 発話終了から3秒無音 (SegmentSilenceMonitor)]
  未送信区間を切り出して MAI Transcribe へ送信 (stt_client.flush())
    -> recognized -> SSE("recognized", session_id, seg-N)
       -> ブラウザ: textarea に逐次追記 (録音を止めずにテキストが確定していく)
    -> 無音が続く間は3秒おきに再発火するが、送るものがなければ何もしない

[再トグル or 10分経過 or 発話終了から2分間無音]
  録音停止 (STTのstop()は呼ばない)
    -> stt_client と専用event_queueをTranscriptionQueueにジョブとしてenqueue
    -> ここで即座にstop_session()が返る (次のstart_session()をすぐ受付可能)
    -> SSE("status", recording=false) をブラウザに送信

[レーン2: 文字起こしワーカー (TranscriptionQueue, FIFO・単一ワーカーで直列処理)]
  ジョブをdequeue -> MAI Transcribe バッチ認識 (stt_client.stop() が
                     flush 済みを除いた残りを最終セグメントとして送信)
    -> recognized  -> SSE("recognized", session_id, seg-N)
       -> ブラウザ: session_idごとの表示キューに蓄積 (先頭セッションのみtextareaに反映)
    -> session_end (session_id付き) をブラウザに送信
    -> ブラウザ: 先頭セッションが完了済みなら (校正ON時) POST /api/proofread で校正
       -> Vertex AI Gemini で校正 -> textarea 更新
    -> ブラウザが session_id + textareaの内容を POST /api/finalize-session で送信
    -> pyperclip にコピー
    -> JSONL に保存 (text フィールドは校正/編集済みテキスト)
    -> 表示キューから除去、次のセッションへ (textareaは次の録音開始まで
       クリアせず、確定済みテキストを表示し続ける)
    -> 次のジョブをdequeue
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

class TranscriptionJob(BaseModel):
    """文字起こし待ちの1セッション分のジョブ (TranscriptionQueueが処理)。"""
    model_config = ConfigDict(arbitrary_types_allowed=True)
    session: RecordingSession
    stt_client: SttEnginePort          # feed_audio済み・stop()未実行
    event_queue: asyncio.Queue[dict[str, str]]  # このセッション専用のSTT結果キュー
    timed_out: bool

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

## 設定値の既定値

反映タイミングの違いによる2種類の区分は「動的設定 (DynamicSettings)」章を参照。

```python
# --- DynamicSettings (~/.voice-input/settings.jsonc、設定タブから変更可能) ---
max_session_duration_sec = 600       # 最大セッション時間 (10分)
silence_timeout_sec = 120            # 発話終了からの無音タイムアウト (2分)
segment_silence_sec = 3.0            # 無音区切り (逐次文字起こし)。上記より小さいこと
vad_threshold = 0.5                  # 発話判定の閾値 (0.0〜1.0)
mai_locale = "ja"                    # 認識ロケール
mai_model_name = "mai-transcribe-1"  # 認識モデル
mai_timeout_sec = 60                 # 認識APIタイムアウト
proofread_timeout_sec = 15           # 校正APIタイムアウト
shutdown_delay_sec = 0.5             # 終了リクエストからプロセス終了までの遅延
sse_keepalive_sec = 15               # SSEキープアライブ送信間隔

# --- Settings (環境変数、変更には再起動が必要) ---
STT_SAMPLE_RATE = 16000              # 音声サンプルレート
VERTEX_LOCATION = "global"               # Vertex AI エンドポイント (preview モデルはグローバルのみ)
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"  # 校正用モデル
```

## アーキテクチャ層構成

`src/` は Domain / Application / Infrastructure / Presentation の4層構成を
取る。境界づけられたコンテキストは単一で、内部を `dictation` (録音・認識・
タイムアウト) / `transcript_history` (確定履歴CRUD) / `proofreading` (校正)
の3モジュールに分割し、各モジュール内をレイヤー化する
(`shared/` は横断的インフラ、`presentation/` はHTTP層)。

```
dictation/
├── domain/            # RecordingSession, Segment, TranscriptionJob, 各種ポート (ABC)
├── application/        # RecordingSessionService, AudioPipelineCoordinator,
│                        # SttEventRelay, SegmentAccumulator, TranscriptionQueue,
│                        # SessionTimeoutMonitor, SegmentSilenceMonitor
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

shared/                 # Settings, Secrets, DynamicSettings +
                         # SettingsRepositoryPort/JsoncSettingsRepository,
                         # ProcessShutdownerPort (横断的)
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

## 文字起こしキュー

録音 (マイク) のライフサイクルと文字起こし処理 (Azure API呼び出しを含む
重い処理) を分離し、文字起こし処理中でも次の録音をすぐに開始できるように
している。

- **`RecordingSessionService`**: 録音の開始/停止のみに責務を絞る。
  `stop_session()` は文字起こし本体 (STTの`stop()`) を待たずに、
  `TranscriptionJob` を `TranscriptionQueue` にenqueueして即座に返る。
- **`AudioPipelineCoordinator`**: セッション開始のたびに専用の
  `asyncio.Queue` を生成し、STTエンジンに渡す。`stop()` は録音停止のみを
  行い、STTクライアントとイベントキューの所有権を呼び出し元に返す
  (STTの`stop()`自体は呼ばない)。
- **`SttEventRelay`**: 録音中のイベントキューを監視し、`interim`/
  `recognized` をリアルタイムにSSE配信する。停止後の残イベント処理は
  行わない。
- **`SegmentAccumulator`**: STTイベントをセグメントに変換しセッションに
  追記する共通ロジック。セグメントIDは `session.segments` の長さから
  算出するため状態を持たず、`SttEventRelay` (録音中) と
  `TranscriptionQueue` (停止後) の両方から呼び出せる。
- **`TranscriptionQueue`**: 文字起こしジョブをFIFOキュー+単一ワーカーで
  直列処理する。ジョブごとにSTTの`stop()`実行、`processing`/
  `processing_done`/`recognized`/`session_end`のSSE配信 (いずれも
  `session_id`付き)、`pending_sessions`への追加を行う。

セッション分離 (`session_id`によるクロスセッション分離): 全SSEイベント
(`status`/`interim`/`recognized`/`processing`/`processing_done`/
`session_end`) に発生元セッションの `session_id` を含める。ブラウザは
`session_id` ごとに独立したテキストを蓄積し、textareaにはキュー先頭の
セッションのみを表示する (詳細は「セッション管理」章参照)。サーバー側の
`AppState.pending_sessions` も単一値ではなく `list[FinalizedSession]` で
保持し、`finalize-session` リクエストの `session_id` で個別に取り出す
(`pop_pending_session`)。これにより、複数セッションの文字起こしが連続
完了しても後発が前発を上書きすることはなく、直列利用・並行利用のいずれでも
各セッションの結果が個別に完全に保存される。

セッションごとに独立した `event_queue` を使う理由: 全セッション共有の
単一キューにすると、あるジョブの `stop()` 実行 (結果put) が別セッションの
`SttEventRelay` の読み出しと重なった場合に、結果を取り違えるリスクがある。
セッションごとにキューを分離することで、処理タイミングがどれだけずれても
取り違えは起きない。

ワーカーを意図的に1本のみに限定している理由: 並列化すると文字起こしの
完了順が録音開始順から崩れる可能性があり、ブラウザの表示キュー
(`sessionQueue`、「セッション管理」章参照) がFIFO順に完了を待つ設計の
前提を満たせなくなるため。

既知の制約 (設計上受け入れているもの):

- **体感遅延**: 直列処理のため、キューに複数ジョブが滞留していると、
  後続ジョブは先行ジョブの処理完了 (最大 `mai_timeout_sec`秒、
  デフォルト60秒) を待ってから処理が始まる。ブラウザの表示キューも
  同様に、先頭セッションが確定するまで後続セッションの内容を表示しない。
- **メモリ**: 録音を連投するとジョブがキューに滞留し、その分のPCM
  バッファ (`MaiTranscribeClient._buffer`) がメモリに残る。滞留数の
  上限は設けない。
- **UI**: キュー内に複数ジョブが滞留していても件数表示等は行わない。

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
| 設定ファイル | 起動時固定の値は環境変数 (`Settings`)。実行中に変更できる値は `~/.voice-input/settings.jsonc` (`DynamicSettings`、設定タブから編集)。詳細は「動的設定」章 |

## 将来課題

- 文字起こし中に次の録音を受け付けてキューイングする機能は
  `TranscriptionQueue` により解消済み (「文字起こしキュー」章参照)。
  `RecordingSessionService.stop_session()` は文字起こし完了を待たずに
  即座に返り、次の `start_session()` をすぐに受け付けられる
- 複数セッションが同時に文字起こし完了待ちになる場合の混線
  (クリップボード/履歴の上書き、textareaでの内容混在) は `session_id`
  によるセッション分離と `pending_sessions` のコレクション化、
  ブラウザ側の表示キュー (`sessionQueue`) により解消済み (「セッション管理」
  「文字起こしキュー」章参照)
- キューは無制限長で、滞留数の上限や録音開始の抑制は行わない
  (「文字起こしキュー」章の既知の制約を参照)
