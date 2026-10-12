# Fraetor リアルタイム化・Herdr 連携・ストリーミングプロンプト 要件定義書

## この文書の読み方

本文書は 3 種の情報を明示的に区別して記載する。混同を避けるため、必ずラベルを確認すること。

| ラベル | 意味 |
|---|---|
| **[要求]** | ユーザーが口述で明示的に述べた要求。改変・補完していない |
| **[現状]** | リポジトリルートのコードを読んで確認した事実。file:line 付き |
| **[未指定]** | ユーザーが述べていないため確定していない事項。推測で埋めていない |

**[未指定]** の項目は実装着手前にユーザーとの合意が必要。本文書の段階では意図的に空欄のまま残している。

> **この文書は2026-08-08時点(コミット `10e5dad`)のスナップショットである。** `[現状]` の `file:line` はその時点のコードに対するもので、その後の実装で行番号やファイル構成は変わっている。
> 例えば `dictation` モジュールは外部ライブラリ [fraetor-dictation](https://github.com/sniper-fly/fraetor-dictation) に切り出し済みで、本文中の `src/dictation/...` は現在 `dictation` パッケージ側にある。
> 現在の設計は `design.md` を参照すること。

## 実装状況 (2026-10時点)

| 機能 | 状況 | 根拠 |
|---|---|---|
| 機能1 無音区間による逐次文字起こし | 実装済み | `SegmentSilenceMonitor` による逐次flush(2026-08-15〜16) |
| 機能2 Vim キーバインド対応エディタ | **未実装** | 該当コードなし |
| 機能3 Herdr 連携によるコピペ不要の送信 | 実装済み | `src/shared/herdr/`(2026-08-18〜24) |
| 機能4 意図翻訳レイヤー | 実装済み | `src/intent_translation/`(2026-08-18〜22)。プロンプトの画面種別対応は `docs/issues/0003` に課題あり |
| 機能5 ストリーミングモード | **未実装** | 該当コードなし |

## 対象機能の一覧

| # | 機能 | 章 | 位置づけ |
|---|---|---|---|
| 機能1 | 無音区間による逐次文字起こし | §2 | 単独実装可 |
| 機能2 | Vim キーバインド対応エディタへの置き換え | §3 | 他機能と独立 |
| 機能3 | Herdr 連携によるコピペ不要の送信 | §4 | 単独実装可 |
| 機能4 | 意図翻訳レイヤー (画面文脈を伴うプロンプト変換) | §5 | 機能1・3 に依存 |
| 機能5 | ストリーミングモード (送信タイミングの AI 判定) | §6 | **別要件の追加機能。機能4 の後に実装** |

**[要求]** 機能4 と機能5 は当初「ストリーミングプロンプト送信」として一体で述べられていたが、後から**別要件として分けたい**という要求があった。分割の境界と根拠は §5.0 に記載。

---

## 1. 背景と現状アーキテクチャ

### 1.1 対象プロジェクト

Fraetorリポジトリ — Linux / macOS 上で動作する常駐型音声入力アプリ。

**[現状]** 全体フロー:

```
DE キーバインド → curl POST /api/toggle-recording
   ↓
FastAPI 常駐プロセス (port 8765)
   ↓ sounddevice で 16kHz/16bit/mono PCM をキャプチャ
   ↓ 同一 PCM を STT と VAD の両方へ分配 (composite sink)
   ↓ 再トグルで停止 → TranscriptionQueue に投入
   ↓ MAI Transcribe へ「セッション全量を 1 リクエスト」で送信
   ↓ SSE recognized → ブラウザ textarea に追記
   ↓ ブラウザが POST /api/proofread (Vertex Gemini 校正)
   ↓ ブラウザが POST /api/finalize-session → pyperclip でコピー + JSONL 保存
```

### 1.2 レイヤ構成

**[現状]** Domain / Application / Infrastructure / Presentation の 4 層クリーンアーキテクチャ。境界づけられたコンテキストは単一で、`dictation` / `transcript_history` / `proofreading` の 3 モジュールに内部分割 (`CLAUDE.md`)。

- 依存方向: Presentation → Application → Domain、Infrastructure → Domain
- Domain はサードパーティ SDK 禁止。純粋な Pydantic モデルとポート (ABC) のみ
- **外部依存を新規追加する場合は必ず対応モジュールの `domain/ports.py` に ABC を定義し `infrastructure/` に実装する** (切り替え予定の有無を問わず一貫して抽象化)
- DI は `dependency-injector` を `src/containers.py` の `Container` に一元化。FastAPI ルートへの `@inject` + `Provide[]` wiring は mypy strict との相性問題で使用禁止。代わりに `src/presentation/app.py:49-59` の lifespan 内で `app.state.*` に手動格納し、ルート側は `request.app.state.X` で取得

→ **本文書の全機能は、この規約に従って新規ポートと実装を追加する形で設計する必要がある。**

### 1.3 既存エンドポイント

**[現状]**

| Method | Path | 実装 | I/O |
|---|---|---|---|
| GET | `/` | `page_routes.py:9` | `index.html` を `read_text()` して `HTMLResponse` (Jinja2 未使用) |
| GET | `/events` | `recording_routes.py:20` | SSE (`sse_starlette.EventSourceResponse`) |
| POST | `/api/toggle-recording` | `recording_routes.py:44` | body なし → `{"recording": bool}` |
| GET | `/api/history` | `history_routes.py:13` | → `list[dict]` (新しい順) |
| DELETE | `/api/history/{session_id}` | `history_routes.py:19` | → `{"deleted": true}` / 404 |
| POST | `/api/proofread` | `proofread_routes.py:26` | `{text}` → `{text, proofread: bool}` |
| POST | `/api/finalize-session` | `proofread_routes.py:34` | `{session_id, text}` → `{ok: bool}` |
| POST | `/api/shutdown` | `shutdown_routes.py:18` | → `{"ok": true}` |

### 1.4 既存 SSE イベント

**[現状]** `sse_broadcaster.py:27` が `{"event": ..., "data": json.dumps(...)}` を全購読者キューに配信。

| event | payload | 発火元 |
|---|---|---|
| `status` | `{recording: true, session_id}` / `{recording: false}` | `recording_session_service.py:86, 134` |
| `error` | `{message}` | `recording_session_service.py:95` |
| `processing` | `{session_id, message}` | `transcription_queue.py:57` |
| `processing_done` | `{session_id}` | `transcription_queue.py:64` |
| `recognized` | `{session_id, segment_id, text}` | `segment_accumulator.py:37` |
| `interim` | `{session_id, text}` | `segment_accumulator.py:29` — **受け側のみ存在。producer は本番コードに存在しない** |
| `session_end` | `{session_id}` | `transcription_queue.py:75` |
| `shutdown` | `{}` | `shutdown_routes.py:32` |
| `keepalive` | `""` | `recording_routes.py:35` |

---

## 2. 機能1: 無音区間による逐次文字起こし

### 2.1 要求

**[要求]** 現状は REST API でリクエストを受け取ったら音声を送って文字起こしする仕組みだが、これをもう少しリアルタイム性のある形にしたい。

- 無音時間が一定 (「例えば 2 秒…いや 3 秒とか」) 続いたら、**そこまでで区切る**
- 区切った時点までの音声を文字起こしして、**エディタに追加する**
- **無音継続時間は設定可能にする**
- 次に喋り始めたら、**前方の無音区間を削除する**。あるいは**喋り始めからきちんと録音して、無音区間を API に送らないようにする**
- 目的は 2 つ:
  1. **API へのリクエスト量を下げる**
  2. **処理時間を早くする**

### 2.2 現状の到達度

#### 既に動くもの

**[現状]** 「無音区間で区切って逐次追記」の**表示側は既に完成している**。

- `SegmentAccumulator` (`segment_accumulator.py:13`) は状態を持たず、`Segment(id=len(session.segments), text=...)` で追記する。`recognized` イベントが N 回来れば N 個のセグメントが積まれる (`:35`)
- 同じメソッドを録音中 (`SttEventRelay` 経由) と停止後 (`TranscriptionQueue.drain` 経由) の両方から呼べる
- ブラウザは `recognized` 受信時に `session.text += data.text` して textarea に追記。**追記前のカーソル位置が末尾でなければ `selectionStart/End` を復元してユーザー編集中のカーソルを保護する** (`index.html:166-180, 266-274`)
- `RecordingSession.full_text` / `FinalizedSession.full_text` は複数セグメントを連結。JSONL も `segments` 配列で保存 (`jsonl_history_repository.py:25`)
- `SttCapabilities.streaming` フィールド (`ports.py:32`) と `interim` イベント型が既に定義済み。`stt/factory.py:25-28` にエンジン分岐の拡張ポイントがコメント付きで用意されている

→ **つまり機能1 で必要な変更はバックエンドの音声分割側に集約される。SSE / ブラウザ / 履歴保存は変更不要。**

#### 既存の VAD

**[現状]** Silero VAD は既に導入済み (`silero-vad>=6.2.1`)。ただし**用途は「無音タイムアウトによる自動録音停止」のみ**。

- `SileroSpeechActivityDetector` (`silero_vad_detector.py:19`)
- `last_speech_time` の消費者は `session_timeout_monitor.py:47` の 1 箇所だけ
- `feed()` は PCM を内部 `bytearray` に蓄積し、**512 サンプル (= 16kHz で 32ms) 単位**で `VADIterator` に投入。余りは次回へ持ち越す (`:38-52`)
- **`VADIterator` は `{'start': ...}` / `{'end': ...}` の辞書を返しており、発話区間の境界情報自体はライブラリから取得できている。しかし `_feed_window` はそれを `last_speech_time` の bool 判定にしか使わず、区間タイムスタンプを破棄している** (`:54-63`)
- VADIterator の未指定パラメータはライブラリデフォルト: `min_silence_duration_ms=100`, `speech_pad_ms=30`。ヒステリシスは `speech_prob < threshold - 0.15` (`.venv/.../silero_vad/utils_vad.py:463-464, 536`)

→ **要求の「無音区間を検知する仕組みは既にあるはず」は正しい。かつ、必要な `start`/`end` タイムスタンプもライブラリから既に得られている。**

#### 障害となる現状

**[現状]** 逐次認識を阻む構造上の制約が 5 点ある。

1. **`MaiTranscribeClient` は完全バッチ。ストリーミング非対応。**
   `_CAPABILITIES = SttCapabilities(streaming=False, post_processing=True)` (`mai_transcribe_client.py:20`)。
   `start()` はバッファをクリアするだけでネットワーク接続をしない (`:60`)。`feed_audio()` は `bytearray` に無制限 append (`:64`)。`stop()` で**セッション全量を WAV 化して 1 回の HTTP リクエストで送信** (`:67`)。
2. **`SttEnginePort` に部分送信 API がない。** メソッドは `start` / `feed_audio` / `stop` の 3 つのみ (`ports.py:39-67`)。`flush()` 相当が存在しない。
3. **`TranscriptionQueue` はセッション単位でしか動かない。** 粒度は `TranscriptionJob` = 1 セッション (`models.py:26`)。フィールドは `session` / `stt_client` / `event_queue` / `timed_out` のみで、部分区間を表す概念 (offset、区間 index、音声バイト列) がない。
4. **`_process_job` が不可分。** `stt_client.stop()` を 1 回呼び、`FinalizedSession` を作り `session_end` を配信する流れが一体化しており、同一セッションへの複数回の部分認識を受け付ける構造ではない (`transcription_queue.py:61-77`)。
5. **VAD と STT が完全に疎結合。** `AudioPipelineCoordinator._on_audio_chunk` (`audio_pipeline_coordinator.py:91`) は同一 PCM bytes を `stt_client.feed_audio()` と `vad.feed()` の両方に同期で投げるだけ。**VAD の判定結果は STT 側に一切フィードバックされない。無音を検知しても STT には何も起きない。**

**[現状]** さらに実行スレッドの制約がある。`_on_audio_chunk` は sounddevice のオーディオコールバックスレッド上で実行される (`sounddevice_base.py:46`)。したがって `flush()` を非同期実行するには `asyncio.run_coroutine_threadsafe` 等でイベントループへスレッドセーフに移送する経路が必要で、**現状のコードにこの経路は存在しない**。

### 2.3 実装余地 (事実ベースの評価)

**[現状]** 最小変更点は 3 箇所に集約される。

| 変更対象 | 内容 |
|---|---|
| `SpeechActivityDetectorPort` (`ports.py:70`) | 「発話終了確定」を通知する手段を追加。VADIterator が既に `{'end': ...}` を返しているので情報は取得済み。**現状破棄している値を渡すだけ** |
| `SttEnginePort` | `flush()` 相当を追加。`MaiTranscribeClient` 側は `_build_wav()` (`:85`) がバッファ内容から WAV を作るだけなので**部分バッファに対してそのまま流用可能** |
| `AudioPipelineCoordinator._on_audio_chunk` (`:91`) | オーディオコールバックスレッド → イベントループへの移送経路を新設 |

変更不要: `SegmentAccumulator` / SSE / `index.html` / JSONL 履歴保存 (いずれも複数セグメント対応済み)。
`TranscriptionQueue` は「最終 flush のみを担う」形に縮小できる。

> 上記は既存構造から導いた評価であり、動作検証はしていない (**未確認**)。

### 2.4 「前方の無音区間を削除」の実現手段

**[現状]** VADIterator は `{'start': sample_index}` を返すため、発話開始位置は取得可能。要求の 2 案 (「後から前方無音を削る」 / 「喋り始めから録音する」) はどちらも VAD の `start` イベントを使えば実現できる。現状はこの値を破棄している (`silero_vad_detector.py:54-63`)。

`speech_pad_ms=30` のデフォルトにより、Silero は発話区間の前後に 30ms のパディングを付ける。過度に切り詰めて語頭が欠けるリスクへの緩衝になる。

### 2.5 要求どおり実装した場合のトレードオフ (要確認)

**[現状]** 要求「API へのリクエスト量を下げる」について、指摘すべき事実がある。

- 現状は **1 セッション = 1 HTTP リクエスト**。無音区間で分割すると **リクエスト数は増える** (N 区間 → N リクエスト)
- 一方で**送信する音声データ量は減る** (無音部分を送らないため)
- したがって「リクエスト量を下げる」が**回数**を指すなら要求と実装は逆方向になる。**データ量 (バイト数 / 課金対象の音声秒数)** を指すなら整合する

**[現状]** 認識精度への影響も未検証。MAI-Transcribe-1 は context biasing 未対応 (`docs/mai-transcribe-1-research.md` §2) のため、分割で文脈が切れて精度が落ちる可能性がある (`docs/paste-latency-research.md` §6 施策2 に同旨の記載)。

**[未指定]**
- 「リクエスト量」がリクエスト**回数**か音声**データ量**か
- 分割による精度低下が許容範囲かどうかの判定基準

### 2.6 設定項目

**[要求]** 無音継続時間は設定可能にする。

**[現状]** 既存の設定機構: `src/shared/config/settings.py` の `Settings` は `ConfigDict(frozen=True)` の Pydantic BaseModel。全項目が必須で、デフォルト値は `load_settings()` 側にハードコードされている。**環境変数で上書きできる項目は一部のみ。**

| 項目 | 既定値 | 環境変数 |
|---|---|---|
| `max_session_duration_sec` | 600 | `FRAETOR_MAX_SESSION_DURATION_SEC` |
| `silence_timeout_sec` | 120 | `FRAETOR_SILENCE_TIMEOUT_SEC` |
| `vad_threshold` | 0.5 | **なし (ハードコード)** |
| `stt_sample_rate` | 16000 | **なし** |
| `mai_locale` | `"ja"` | なし |
| `mai_model_name` | `"mai-transcribe-1"` | なし |
| `mai_timeout_sec` | 60 | なし |
| `server_host` | `"127.0.0.1"` | なし |
| `server_port` | 8765 | `FRAETOR_SERVER_PORT` |
| `shutdown_delay_sec` | 0.5 | なし |
| `sse_keepalive_sec` | 15 | `FRAETOR_SSE_KEEPALIVE_SEC` |
| `vertex_location` | `"global"` | なし |
| `gemini_model` | `"gemini-3.1-flash-lite-preview"` | なし |
| `proofread_timeout_sec` | 15 | なし |
| `proofread_prompt` | 既定プロンプト | なし |
| `history_dir` | `~/.voice-input` | `FRAETOR_HISTORY_DIR` |

→ 新設する「無音区切り閾値」もこの `Settings` に追加する。既存の `silence_timeout_sec` (無音 120 秒で自動録音停止) とは**別概念**であり、名前が衝突しないよう区別が必要。

**[未指定]**
- 新設する無音区切り閾値のデフォルト値 (「2 秒、いや 3 秒とか」と言い直したのみで確定していない)
- 設定の変更手段 (環境変数 / ブラウザ UI / 設定ファイル)
- 既存の `silence_timeout_sec` (120 秒) との関係。逐次認識導入後もセッション全体の無音タイムアウトを維持するか

---

## 3. 機能2: Vim キーバインド対応エディタへの置き換え

### 3.1 要求

**[要求]**

- 今は普通の textarea。これを **Vim のキーバインドが使えるエディタ形式**にしたい
- 要するに **Vim と同じようなものが使えて、かつ VS Code のようなエディタ**になるように
- **yank したものとクリップボードを共有**できるようにしたい
- できれば **Vim のキーバインド自体も設定可能**にしたい
- **`j` / `k` が「論理行の 1 行」ではなく、折り返しを含めた画面表示上の 1 行を移動する挙動をデフォルトにしたい**
  - 理由: 文字起こしの文章は基本的に 1 行で送信されるので、普通に `j` を押すと全体の一番下に飛んでしまい不便
- 実装方針: 今はフロントエンドに凝ったライブラリを使っていないので、**React 等を使う変更や抜本的なフロントエンド入れ替えを伴ってもよい**
- 優先基準: **実現しやすく、保守しやすく、自前実装が少ない形**

### 3.2 現状のフロントエンド

**[現状]** フロントエンドは `src/templates/index.html` の**単一ファイル 401 行**に完結している。

- **ライブラリは Tailwind CSS CDN 1 本のみ** (`:7` `<script src="https://cdn.tailwindcss.com">`)。React / Vue / Alpine 等なし
- **ビルドパイプラインが存在しない。** `package.json` / `package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` / `vite.config.*` / `webpack.config.*` / `tsconfig.json` すべて 0 件。`node_modules/` なし。ロックファイルは `uv.lock` のみ
- **リポジトリ内の `.js` / `.ts` / `.css` / `.jsx` / `.tsx` ファイルは 0 件**
- JS は完全に inline (`:70`-`:399` の単一 `<script>`)。モジュール化なし (トップレベル関数 + トップレベル `let`)
- FastAPI 側に `StaticFiles` マウントも `Jinja2Templates` もなし。`page_routes.py:9-13` が `index.html` を素読みして返すだけ
- 依存関係は Python のみ (本体 15 / dev 12)。**フロントエンド依存はゼロ**

→ **要求の「今はあまり凝ったライブラリを使っていない」は正確。抜本的入れ替えを許容するなら、ビルドツール導入を含めてゼロから設計できる。**

### 3.3 textarea の現在の実装

**[現状]**

- `#editor-textarea` (`:48-50`, `rows="8"`, `resize-y`, placeholder `"待機中..."`)
- 直下に `#editor-interim` (`:51-53`) — 中間結果を読み取り専用で表示する div
- `appendToTextarea()` (`:166-180`) — 追記前カーソル位置が末尾なら末尾追従、それ以外は `selectionStart/End` を復元
- `updateEditorInterim()` (`:182-189`) — `escapeHtml(text) + ' <span>[認識中]</span>'` を `innerHTML` に注入

**セッション表示キューのロジック** (`:191-254`) — エディタ置き換えで最も注意すべき既存ロジック:

- 状態 3 つ: `sessionQueue = []` (要素 `{id, text, ended}`)、`finalizing = false`、`displayedSessionId = null`
- **先頭 (`sessionQueue[0]`) のみ表示。** 完了順に 1 件ずつ自動確定 (校正 → finalize)
- **textarea のクリアは「表示セッションが切り替わる瞬間」のみ。** finalize 直後にはクリアしない (確定テキストを見せ続ける設計)
- `tryAdvanceQueue()` (`:219-254`): `finalizing` ガード → 先頭を表示 → `!ended` なら return → `finalizing = true` → 校正 ON かつ非空なら `POST /api/proofread` → `POST /api/finalize-session {session_id, text: textarea.value}` → `shift()` → `finalizing = false` → 自己再帰

→ **エディタを置き換える場合、このキュー管理と「カーソル位置を保持したまま外部から末尾追記する」機能を新エディタ上で再実装する必要がある。**

### 3.4 現在の UI 要素一覧

**[現状]** 新 UI 設計時に引き継ぐべき既存要素:

| 要素 | id | 挙動 |
|---|---|---|
| タブ | `#tab-main` `:15` / `#tab-history` `:17` | `switchTab()` `:71` でパネルを `hidden` 切替。履歴タブ選択時に `loadHistory()` |
| 録音インジケータ | `#rec-indicator` `:26` / `#rec-label` `:27` | 灰丸「停止中」/ 赤丸 `animate-pulse`「録音中」 |
| 校正トグル | `#proofread-toggle` `:31` | `localStorage['proofreadEnabled']`、既定 ON |
| コピーボタン | `#btn-copy-main` `:36` | `navigator.clipboard.writeText` |
| シャットダウン | `#btn-shutdown` `:39` | `confirm()` → `POST /api/shutdown`。**録音中は disabled** |
| 履歴削除 | 履歴カード内 | `DELETE /api/history/{id}` |
| トースト | `#copy-toast` `:65` | 1.5 秒で消える |

### 3.5 既知の結合点 (置き換え時の破壊対象)

**[現状]** **`index.html` の DOM id と Tailwind クラス名は E2E テストが直接参照している。**

`tests/e2e/test_browser_ui.py` が参照 (`:38, 59, 93, 95, 99, 118, 197, 241`):
`#editor-textarea`, `#tab-history`, `#history-list`, `#btn-copy-main`, `#copy-toast`
さらに Tailwind クラスセレクタ `div.bg-gray-800` / `div.text-sm` にも依存 (`:124-125`)。

→ **エディタ置き換えは E2E テストの書き換えを必然的に伴う。**

**[現状]** `CLAUDE.md:27` — `pytest-playwright` (同期 API) と `pytest-asyncio` に既知の非互換があるため、E2E は README 記載の 2 コマンド分割 (`--ignore=tests/e2e/test_browser_ui.py` と単独実行) が必須。1 コマンドでの一括実行はできない。

**[現状]** 履歴カードのレスポンス形状は Pydantic 未定義。`jsonl_history_repository.py:17-26` の生 dict (`id`, `started_at`, `ended_at`, `timed_out`, `text`, `segments[]`) がそのまま `GET /api/history` に流れ、`index.html:339-347` が `s.started_at` / `s.text` / `s.id` を読む。**契約はコードの暗黙合意のみ。** フロント入れ替え時にレスポンスモデルを明示化する機会になる。

### 3.6 技術的補足: 要求の各項目の実現手段

**[現状]** 「折り返しを含めた画面表示上の 1 行を `j`/`k` で移動する」という要求は、Vim の `gj` / `gk` (screen line 単位移動) に相当する挙動をデフォルトの `j` / `k` に割り当てることを意味する。要求の背景説明 (「文字起こしの文章は基本的に 1 行で送信される」) は正しい — `RecordingSession.full_text` は**セグメントを区切り文字なしで `"".join()` する** (`dictation/domain/models.py:22`) ため、改行が入らず 1 論理行になる。

**[未指定]**
- 採用するエディタライブラリ (要求は「実現しやすく保守しやすく自前実装が少ない形」という基準のみ提示)
- React を導入するか否か (「使うような変更があってもいい」という許容の表明であり、指定ではない)
- ビルドツールの選定、Tailwind を CDN のままにするかビルドに含めるか
- Vim キーバインド設定の永続化先 (`localStorage` / サーバ側設定ファイル / `Settings`)
- 「VS Code のようなエディタ」に何を含めるか (シンタックスハイライト、複数カーソル、ミニマップ等のどこまでを指すか)
- クリップボード共有の方向 (yank → OS クリップボード、OS クリップボード → paste、双方向のいずれか)

---

## 4. 機能3: Herdr 連携によるコピペ不要の送信

### 4.1 要求

**[要求]** 動機: **コピペでいちいちペースト先を選んで毎回ペーストするのが手間**なので、録音停止と同時に送信できるようにしたい。

- Herdr の API を使い、文字起こし結果を**そのまま Herdr のターミナルに送信**する
- Fraetor 画面上に**現在有効な Herdr セッションを表示**する
- ボタン、もしくは REST エンドポイントを受けた時に、**今一番前面に出ている Herdr セッション**に文字起こし結果を送信する
- これは**通常の文字起こし完了エンドポイントとは区別して設ける**

#### トグル方式のエンドポイント

**[要求]** 既存の `toggle-recording` が 1 エンドポイントで録音開始/終了を表現しているのと同じ考え方で、**1 つのエンドポイントで 2 役**を担う。

| 呼び出し | 動作 |
|---|---|
| 1 回目 | **送信先の Herdr セッションを確定**し、**同時に録音を開始**する |
| 2 回目 (同一エンドポイント) | あらかじめ決めた Herdr セッションに対して**文字起こし結果の送信を確定**する |

**[要求]** 仮に**通常のトグルインプット (`/api/toggle-recording`) が押された場合は、Herdr へ送信せず普通に録音を停止するだけ**。

#### その他 UI

**[要求]**

- 上記とは別に、**手動の送信ボタン**を 1 つ設ける (画面上の文字をどのセッションに送信するかを決定するボタン)
- **Herdr セッション選択の UI** も 1 つ欲しい

### 4.2 Herdr の技術仕様 (既存調査済み)

**[現状]** `docs/paste-latency-research.md` (調査日 2026-07-30) に一次情報検証済みの調査結果が既に存在する。以下はその要約。

#### 実体

| 項目 | 内容 |
|---|---|
| リポジトリ | `herdrdev/herdr` (Apache-2.0) |
| 正体 | agent multiplexer。Rust 製の単一バイナリ |
| 公式サイト | https://herdr.dev |
| 対応 OS | macOS / Linux / Windows (beta) |
| インストール | `brew install herdr` / `mise use -g herdr` / `curl -fsSL https://herdr.dev/install.sh \| sh` |

ワークスペース / タブ / ペインで端末を組織化し、ペイン内のコーディングエージェントを認識して意味的状態 (`idle` / `working` / `blocked` / `done` / `unknown`) を管理する。

#### Socket API

出典: https://herdr.dev/docs/socket-api/

- **プロトコル**: newline-delimited JSON over local socket (Unix domain socket / Windows named pipe)
- **ソケットパス**: `~/.config/herdr/herdr.sock` (デフォルト) / `~/.config/herdr/sessions/<name>/herdr.sock` (名前付き)
- **解決優先順位**: CLI `--session` → `HERDR_SOCKET_PATH` → `HERDR_SESSION` → デフォルト
- 形式: `{"id":"req_1","method":"ping","params":{}}` → `{"id":"req_1","result":{"type":"pong"}}`

#### 「一番前面に出ているセッション」の取得

**[現状]** `session.snapshot` の `SessionSnapshot` 構造体 (`src/api/schema/session.rs`、実装ソースで確認) に以下がある:

```rust
pub struct SessionSnapshot {
    pub focused_workspace_id: Option<String>,
    pub focused_tab_id: Option<String>,
    pub focused_pane_id: Option<String>,   // ← 要求の「今一番前面に出ている」に対応
    pub workspaces: Vec<WorkspaceInfo>,
    pub tabs: Vec<TabInfo>,
    pub panes: Vec<PaneInfo>,
    pub agents: Vec<AgentInfo>,
}
```

→ **要求の「1 回目の呼び出しで送信先セッションを確定する」は `focused_pane_id` を記録することで決定論的に実現できる。AI による宛先判断は不要。**

#### テキスト投入 API

出典: `docs/next/website/src/content/docs/cli-reference.mdx` (公式リポジトリ)

| コマンド | Enter 送信 | 備考 |
|---|---|---|
| `herdr agent prompt <target> <text>` | **する** | bracketed-paste モードを尊重し、テキスト + Enter をアトミックに送信。**エージェントが working 中でも送信可能** |
| `herdr pane send-text <pane_id> <text>` | しない | 低レベル。投入のみ |
| `herdr pane run <pane_id> <command>` | する | 通常コマンド用 |

`agent prompt` の `target` は「一意な live エージェント名」または「そのエージェントを現在ホストしているペイン ID」を受け付ける。記録した `focused_pane_id` をそのまま宛先に使える。

#### セッション一覧取得 (画面表示用)

**[現状]** 要求の「現在有効な Herdr セッションを表示」「セッション選択 UI」に使える API:

- `herdr agent list` — live エージェントを列挙
- `herdr agent get <target>` / `herdr agent read <target>` — 状態と出力の取得
- `pane.list` / `pane.get` — レスポンスに `agent_status` と `agent_session` が含まれる

#### ID 体系

**[現状]** 公開 ID は不透明かつ安定なハンドル: workspace `w1` / tab `w1:t1` / pane `w1:p1`。

閉じたタブ・ペインの ID は再利用されない。ただし**ペインを別ワークスペースへ move すると新しいワークスペース修飾つき ID が振られる** (`pane move` 後は `.result.move_result.pane.pane_id` を使う)。

→ **1 回目の呼び出しから 2 回目までの間にペインが move されると宛先 ID が無効になる。** 投入直前の生存確認かフォールバックが必要。

#### 環境変数

**[現状]** Herdr は管理下プロセスに `HERDR_ENV=1`, `HERDR_SOCKET_PATH`, `HERDR_WORKSPACE_ID`, `HERDR_TAB_ID`, `HERDR_PANE_ID` を注入する。

**ただし Fraetor サーバーは `toggle-recording.sh:23` で `nohup uv run fraetor &` として起動されるため、Herdr ペイン内で起動されない可能性がある。サーバープロセスの環境変数に依存せず、ソケットパスを直接解決する実装が必要。**

### 4.3 既存調査で決めてある設計方針

**[現状]** `docs/paste-latency-research.md` §8。ただし**これは調査レポート内の推奨であり、ユーザーが口述で述べた要求ではない**。実装時に採否を判断する材料として記載する。

#### テキスト出力先の抽象化

`AudioCapture` と同じパターンを踏襲:

```
TextSink (抽象基底)
  ├─ ClipboardSink   … 既存 PyperclipClipboard
  └─ HerdrPaneSink   … Herdr socket / CLI 経由で投入
```

- ファクトリが環境を判定して実装を選択 (`create_audio_capture()` と同じ構造)
- Herdr 未導入 / ソケット不在なら `ClipboardSink` へ自動フォールバック
- 投入失敗時も `ClipboardSink` へフォールバックし、テキストを失わない

#### 宛先の記録

`RecordingSession` に `target_pane_id: str | None = None` を追加し、録音開始時の `focused_pane_id` を記録する。取得失敗はエラーにせず `None` (= クリップボード経由) とする。

### 4.4 現状の制約と要検討事項

**[現状]** 現状のクリップボードコピー経路: `finalize_session_use_case.py:22` が `clipboard.copy(text)` → `history_repository.save(...)`。**両方とも try/except で例外を握り潰す** (`:25, :29`)。

**[現状]** 重要: **クリップボードコピーはブラウザからの `POST /api/finalize-session` が来ないと発生しない。サーバー側の自動コピー経路は存在しない** (`index.html:245` が起点)。

→ **要求の「REST エンドポイントを受けた時に送信」を実現するには、ブラウザを経由しないサーバー主導の送信経路を新設する必要がある。** これは現状のアーキテクチャにない流れ。

**[現状]** `AppState.pending_sessions` はブラウザが `finalize-session` を送るまで無限に溜まる。TTL / 上限なし (`app_state.py:16`)。

**[現状]** 校正との関係の制約 (`docs/paste-latency-research.md` §6, §8.3):

- 現状は `session_end` → 校正完了 → `finalize-session` (コピー) の直列。校正タイムアウトは 15 秒
- 認識完了時点で先に送信し、校正結果を後追いで置き換える方式にすれば体感待ち時間をほぼ削れる
- **ただし Herdr 送信と組み合わせると「未校正テキストが即座にエージェントへ送信される」ことになる。校正済みを送りたいならノンブロッキング校正と Herdr 送信は排他になる**

**[未指定]**
- **エンドポイントのパスと名前**
- **2 回目の呼び出しで「送信を確定」した際に、録音を停止するのかどうか。** 要求は「送信を確定する」とのみ述べており、録音停止との関係が明示されていない
- **投入コマンドの選択**: `agent prompt` (Enter 送信あり = 即実行) か `pane send-text` (目視確認後に自分で Enter) か
- **校正との関係**: Herdr 送信時に校正完了を待つか、未校正で即送信するか
- **ペイン ID の生存確認**: 投入直前に `pane.get` で存在確認するか、失敗時フォールバックのみで済ませるか
- **「手動の送信ボタン」と「セッション選択 UI」の関係**: 別要素として 2 つなのか、選択 UI で選んでボタンで送るという一体の流れなのか
- Herdr セッション一覧の更新契機 (ポーリング / SSE / 開くたび取得)
- 送信失敗時のユーザーへのフィードバック方法

---

## 5. 機能4: 意図翻訳レイヤー (画面文脈を伴うプロンプト変換)

### 5.0 機能分割の経緯

**[要求]** 当初この機能は「ストリーミングプロンプト送信」として一体で述べられていたが、後から**2 つの独立した機能に分けたい**という要求があった。分割の根拠はユーザー自身の整理による:

> 技術的には、手動でコーディングエージェントに音声認識結果を入力するか Herdr の API を通じて入力するか、**その意味のある入力単位を AI 自身に判定させて送信処理を AI に任せるか**。この後者がストリーミングモードとした概念であり、実際これがなくてもかなりのスピードで AI にやりたいことを入力できるはずだから、まずはストリーミングモードなしでその機能を実現したい。

**[要求]** したがって分割の境界は以下のとおり。

| | 機能4 (本章) | 機能5 (§6) |
|---|---|---|
| 内容 | 音声認識結果 + 画面文脈を**コーディングエージェント向けプロンプトに翻訳する層** | **送信タイミングの判定を AI に任せる**仕組み |
| 送信の主体 | **人間** (手動送信ボタン / Herdr 連携トグル = 機能3) | **AI** (意味のある入力単位になったと判定したら自動送信) |
| 位置づけ | 先に実装する | **次の追加機能として別に実装する** |

**[要求]** 「リアルタイム送信するか、ストリーミング的な送信をするかどうかっていうのは、次の追加機能として別に実装した方が、機能としては別で考えて実装した方が良さそう」。

### 5.1 解決したい課題

**[要求]**

- PR レビュー中、「このコードがどういう繋がりがあるのか」「全体の中でどういう位置づけか」「なぜここにあるのか」「似たようなパターンがあるのか」といった疑問を、いちいち **AI に伝わる形式に翻訳してチャットで叩いて結果を読む**という流れになっている
- この **AI に自分の意図を伝える時間**がかかりすぎて、レビュー速度がその分遅くなる
- これを**音声認識による高速インプットとスクリーンショットの活用**で、**高速かつ正確に AI に意図を伝える**形にしたい

### 5.2 要求

**[要求]**

- **録音ボタンを押した時から継続的に、何秒かに 1 回スクリーンショットを撮る**
- **スクリーンショットと入力結果 (音声認識結果) の対応をしっかりつける**
- **マウスがどこにあるか、ユーザーがどこを見ていそうか、何について話しているのか**といった情報を捉える
- それらを踏まえて**翻訳するレイヤーを追加する**

補足として述べられた要求:

- 例: VS Code の画面を見て、ユーザーが今画面上でどの **Git 差分**を見ているのか。「この関数は」「ここ」「そこ」が何を指しているのか
- **音声認識にタイムスタンプと認識結果の対応が取れるのであれば、それを活用する**
- スクリーンショットと生の認識結果をそのままコーディングエージェントに送ると、画像 + 整形前の文章になり**コンテキストの無駄が非常に大きい**
- そこで**画像認識可能な LLM** で、ユーザーが見ていた画面スクリーンショットと認識結果を「**ユーザーのやりたいこと・聞きたいこと**」= **コーディングエージェント向けプロンプト**に変換するレイヤーを作る

### 5.3 動作フロー

**[要求]** 送信の起点は人間である点が機能5 との違い。

1. 録音を開始する
2. **録音開始時点から、何秒かに 1 回スクリーンショットを撮り続ける**。同時にマウス位置等の画面文脈も取得する
3. 喋ると、無音区間ごとに認識結果がテキストエリアに継ぎ足されていく (機能1 が前提)
4. スクリーンショットと音声認識結果の**対応 (時系列上の紐付け)** を保持する
5. **人間が送信操作を行う** — 手動の送信ボタン、または機能3 の Herdr 連携トグル (2 回目の呼び出し)
6. その時点で、蓄積したスクリーンショット + 認識結果を**画像認識可能な LLM に通してコーディングエージェント向けプロンプトに変換**する
7. 変換結果を Herdr 経由でコーディングエージェントに送る (機能3)

### 5.4 機能4 の技術課題: 翻訳層 (非決定論的処理)

**[要求]**

- スクリーンショットと生の認識結果をそのまま送るとコンテキストの無駄が大きいため、**画像認識可能な LLM** による変換レイヤーが必要
- 変換の出力は「ユーザーのやりたいこと・聞きたいこと」に整形されたプロンプト

→ これは**単一の非決定論的判定**であり、送信タイミング判定 (機能5 の判定) とは独立している。

### 5.5 現状の技術資産と欠落

#### 既にあるもの

**[現状]** LLM 呼び出しの基盤は既に存在する。

- `google-genai>=1.71.0` が本体依存に入っている
- `VertexGeminiProofreader` (`proofreading/infrastructure/vertex_gemini_proofreader.py:37`) が Vertex AI Gemini を呼び、`response_schema=ProofreadResult` の**構造化出力**を使っている
- 使用モデルは `settings.gemini_model = "gemini-3.1-flash-lite-preview"`
- 認証は AWS SSM Parameter Store から Vertex サービスアカウント JSON を取得 (`secrets_loader.py:15-17`、参照する環境変数は `FRAETOR_SSM_MAI_API_KEY` / `FRAETOR_SSM_MAI_ENDPOINT` / `FRAETOR_SSM_VERTEX_SA` で、値はパラメータ**名**)
- `ProofreadTextUseCase` (`proofreading/application/proofread_text_use_case.py:22`) は校正器未設定・例外・タイムアウト時に元テキストを返すフォールバック構造を持つ。**LLM 呼び出しの失敗を機能停止にしない設計パターンが既にある**

→ **翻訳層は `proofreading` モジュールと同じ構造 (domain/ports.py に ABC → infrastructure に Vertex 実装 → application にユースケース) で追加できる。** Gemini は画像入力に対応しているため画像を含む変換も同じ経路で実現しうる (**画像入力の実装は未検証 = 未確認**)。

#### 欠落しているもの

**[現状]**

1. **スクリーンショット撮影機能はリポジトリ内に一切存在しない。** 関連する依存関係もない (本体依存 15 個に画面キャプチャ系ライブラリなし)
2. **マウス位置取得機能も存在しない。**
3. **音声認識結果にタイムスタンプが付いていない。** `Segment` (`dictation/domain/models.py:9`) は `id: int` と `text: str` のみ。`RecordingSession` は `started_at` を持つが、セグメント単位の時刻情報はない。MAI からのイベントも `{"type": "recognized", "text": text}` のみ (`mai_transcribe_client.py:82`)

→ **要求の「音声認識にタイムスタンプと認識結果の対応が取れるのであれば」という条件付きの言い方に対する回答: 現状は取れていない。機能1 の実装で無音区間ごとに区切るなら、区切りの発生時刻をセグメントに記録することで取得可能になる。** (VAD が既に `{'start'}`/`{'end'}` を返している → §2.2)

**[現状]** スクリーンショット撮影のプラットフォーム上の制約 (`docs/paste-latency-research.md` §4 に関連記述):

- macOS: 画面収録権限 (Screen Recording) が必要
- Linux Wayland: 統一 API がなくコンポジタ依存。合成キー入力についても「Wayland 環境では手段が確立していない」と結論されている
- 現状 `README.md:3` は「Linux 上で動作する」と記述。コード上は macOS 対応あり (`audio/factory.py:25-27` — darwin は `PersistentStreamCapture`、Linux は `PerSessionStreamCapture`)

→ **スクリーンショット撮影は音声キャプチャと同様にプラットフォーム分岐が必要になる見込み。**

**[現状]** コンテキスト量に関する参考実測 (`docs/paste-latency-research.md` §3、`~/.voice-input/history.jsonl` の 2,095 セッション):

| 統計量 | 録音時間 (秒) | 文字数 |
|---|---|---|
| 10 %ile | 7.5 | 22 |
| 50 %ile | 27.4 | 81 |
| 90 %ile | 111.6 | 286 |
| 最大 | 207.7 | 2,099 |

→ 録音時間の 90 %ile が 112 秒。「何秒かに 1 回」の撮影間隔を仮に 5 秒とすると 1 セッションで 20 枚超になる。**翻訳層に渡す画像枚数の上限・間引き方針が必要。**

**[現状]** 現状の校正は `PROOFREAD_TIMEOUT_SEC = 15` 秒で、これが貼り付け待ち時間に直列で載っている (`docs/paste-latency-research.md` §3, §6)。翻訳層は画像を伴うためこれより重くなる見込み。**「高速に AI に意図を伝える」という目的に対し、翻訳層の遅延が新たなボトルネックになりうる。**

### 5.6 未指定事項

**[未指定]**

- 翻訳層に使う具体的なモデル (「画像認識可能な LLM」という要求のみ)
- **スクリーンショットの撮影間隔** (「何秒かに 1 回」という要求のみで秒数未確定)
- **スクリーンショットの撮影対象範囲** (全画面 / アクティブウィンドウ / マウス周辺 / マルチディスプレイの扱い)
- 翻訳層に渡す画像の枚数上限と間引き方針
- マウス位置情報の取得方法と、LLM への渡し方 (座標を数値で渡す / 画像上にマーカーを描画する等)
- 「ユーザーがどこを見ていそうか」の推定に使う情報源 (マウス位置以外に何を使うか。視線追跡は想定していないと理解しているが未確認)
- スクリーンショットの保存・破棄ポリシー (履歴に残すか、送信後に破棄するか。**画面内容を含むためプライバシー観点の判断が必要**)
- 翻訳層を通すか通さないかの切り替え方法 (常時 ON / UI トグル / 別エンドポイント)
- 翻訳層の出力をユーザーが確認・編集できるか (そのまま送るか、textarea に出して目視後に送るか)
- 翻訳層のタイムアウト値と失敗時の挙動 (校正と同じく原文フォールバックとするか)
- 翻訳層と既存の校正機能の関係 (両方通すか、翻訳層が校正を包含するか)
- 機能3 の手動送信ボタン / Herdr トグルのどちらを翻訳層の起動契機にするか (両方か片方か)

---

## 6. 機能5: ストリーミングモード (送信タイミングの AI 判定)

**[要求]** これは**機能1〜4 とは別要件の追加機能**として、後から実装する。

### 6.1 機能4 との境界

**[要求]** 機能4 との違いは**送信タイミングを誰が決めるか**の一点に集約される。

> その意味のある入力単位を **AI 自身に判定させて送信処理を AI に任せるか**。この後者がストリーミングモードとした概念であり、実際これがなくてもかなりのスピードで AI にやりたいことを入力できるはず。

| | 機能4 | 機能5 (本章) |
|---|---|---|
| 送信の起点 | 人間 (ボタン / Herdr トグル) | **AI の判定** |
| 翻訳層 | 使う | 使う (機能4 を再利用) |
| 実装順 | 先 | **後** |

→ **機能5 は機能4 の上に「自動送信トリガー」を載せるものであり、翻訳層そのものを重複実装しない。**

### 6.2 要求

**[要求]**

- 音声認識結果が**意味のあるユーザーの意思を汲み取り可能な音声ブロックになったかどうかを判定**する
- フィラーワードだけが音声になった場合、意味のない単語なのでそのまま LLM に投げても意味がない
- **軽量・高速な LLM** を用いて判定を行う
- 無音区間ごとに文字が足されていく認識結果を、一度 LLM に通して意味のある音声単位かどうかを判定し、**送信するかどうかを自動的に決める**
- 意味のあるまとまりになったら、**逐次コーディングエージェントに投げる** (Herdr API 経由 = 機能3)

**[要求]** ユーザーが挙げた「意味のある単位」の具体例:

- 「この関数はなんで必要なのか」
- 「この関数はどこから来ていて、なぜ追加されたのか」
- 「引数のパターンが…引数が多い」
- 「依存性注入がちゃんとできてない」
- 「これはどこで再評価されるのか」
- 「これはキャッシュなのか」

### 6.3 モードとしての位置づけ

**[要求]**

- これは**ストリーミングモード**として実装する
- **コードレビューをしているときに有効なモード**
- レビュー中の**ボソボソした独り言をしっかりと時系列で記録**し、**かすかな疑問を見逃さず**、かつすぐにコーディングエージェントに聞ける
- 前提: **無音区間が検出され、認識結果がぶつ切りでテキストエリアに反映されること** (機能1)

### 6.4 現状の技術資産と欠落

**[現状]** 判定用の軽量 LLM 呼び出し基盤は既にある。`settings.gemini_model = "gemini-3.1-flash-lite-preview"` は**既に軽量・高速モデル**であり、要求の「軽量高速の LLM」にそのまま流用できる可能性がある (`vertex_gemini_proofreader.py:37` と同じ経路)。

**[現状]** `response_schema` による構造化出力が既に使われている (`ProofreadResult`)。判定結果 (送信すべきか否かの真偽値) も同じ仕組みで受け取れる。

**[現状]** **モード切り替えの受け皿がない。** `AppState` (`app_state.py:11`) は `broadcaster` / `current_session` / `recording` / `pending_sessions` のみで、モード概念を持たない。

**[現状]** 逐次送信の制御に使える Herdr 側の情報: `pane.list` / `pane.get` のレスポンスに `agent_status` (`idle` / `working` / `blocked` / `done` / `unknown`) が含まれる。また `herdr agent prompt` は**エージェントが working 中でも送信可能** (`docs/paste-latency-research.md` §5.3)。

→ **「working 中でも送れる」ことは、逐次送信を実現する上では利点だが、同時に「エージェントが処理中に次のプロンプトを積む」制御を Fraetor 側で判断する必要があることも意味する。**

### 6.5 未指定事項

**[未指定]**

- 判定に使う具体的なモデル (「軽量高速の LLM」という要求のみ)
- 判定の呼び出し契機 (無音区間ごとに毎回か、一定の文字数 / 時間の閾値を超えたときか)
- 判定が「意味がない」と判定したテキストの扱い (破棄 / 次の区間と結合して再判定 / テキストエリアには残す)
- 判定の誤りをユーザーが訂正・介入する手段 (誤って送信された場合の取り消し、送信前の確認)
- **ストリーミングモードと他モードの切り替え方法** (UI トグル / 別エンドポイント / 起動時設定)
- ストリーミングモード中の履歴保存の仕様 (通常セッションと同じ JSONL に混ぜるか)
- ストリーミングモード中の校正機能の扱い
- 送信先 Herdr セッションの決定方法 (機能3 のトグルと同じ仕組みか、モード開始時に固定するか)
- 逐次送信でコーディングエージェント側が飽和した場合の制御 (レート制限、`agent_status` を見た抑制など)
- ストリーミングモードでのセッション時間上限 (現状 `max_session_duration_sec = 600` = 10 分。レビュー中ずっと録音する用途と整合するか)
- 判定 LLM の呼び出し頻度と累積コストの許容範囲

---

## 7. 機能間の依存関係

### 7.1 依存グラフ

```
機能1 (無音区間による逐次認識)
  ├─ 前提なし。単独で実装可能
  ├─→ 機能4 に音声認識結果のタイムスタンプを供給
  │    (セグメント区切り時刻を記録できるようになる → §5.5)
  └─→ 機能5 の前提 (ユーザーが明言: 「無音区間が検出されていて認識結果が
       ぶつ切りでテキストエリアに反映されることが前提」)

機能2 (Vim エディタ)
  └─ 他機能と独立。ただしフロントエンド全面入れ替えを伴うため、
     機能3・機能4 の UI 追加と同時進行すると衝突する

機能3 (Herdr 連携)
  ├─ 前提なし。単独で実装可能
  └─→ 機能4・機能5 の送信経路として使われる

機能4 (意図翻訳レイヤー)
  ├─ 機能3 に依存 (送信経路)
  ├─ 機能1 に依存 (認識結果とスクリーンショットの時系列対応)
  └─→ 機能5 が再利用する (翻訳層そのものは機能4 で完成させる)

機能5 (ストリーミングモード = 送信タイミングの AI 判定)
  └─ 機能1・機能3・機能4 のすべてに依存。最後に実装する
```

### 7.2 実装順序

**[要求]** 機能5 の位置づけは明示されている: **「まずはストリーミングモードなしでその機能を実現したい」** ため、機能5 は機能4 の後。

**[未指定]** 機能1〜4 の相互の優先順位。ユーザーは列挙したのみで順序を述べていない。

**[現状]** 参考として、`docs/paste-latency-research.md` §7 の推奨着手順 (調査レポートの推奨であり、ユーザーの指定ではない):

| 順 | 施策 | 理由 |
|---|---|---|
| 1 | 待ち時間の実測ログ追加 | MAI 認識時間と校正時間を分離記録。現状どちらが支配的か未確認 |
| 2 | 校正のノンブロッキング化 | 実装が軽く効果が確実 |
| 3 | Herdr 配送 (= 本文書の機能3) | 待ち時間を作業からデカップリング |
| 4 | チャンク分割認識 (= 本文書の機能1) | 実装コストが最も高く、精度への影響検証も必要 |

**[現状]** 計測の欠落: MAI 認識時間と校正時間を分離して記録しておらず、`fraetor-server.log` も存在しない。**体感 20 秒の待ち時間のうち認識と校正のどちらが支配的かは未確認。**

---

## 8. 実装時の遵守事項

**[現状]** `CLAUDE.md` および `pyproject.toml` から確認した制約。

### 設計規約

- **dataclass ではなく Pydantic の `BaseModel` を使う**
- **プライベート関数を乱立させない。関心が異なるモジュールは別クラス・別モジュールにする**
- **外部依存の新規追加時は必ず `domain/ports.py` に ABC を定義し `infrastructure/` に実装する** (切り替え予定の有無を問わず一貫して抽象化)
  → 機能3 の Herdr クライアント、機能4 のスクリーンショット撮影・マウス位置取得・判定 LLM・翻訳 LLM は**すべてポート化が必須**
- DI は `src/containers.py` の `Container` に一元化。手動 DI を `app.py` / `__main__.py` に直接書くのは禁止。`src/containers.py` のみ型安全性の緩和を許容
- **依存関係追加は `pyproject.toml` を直接編集せず `uv add` で最新安定版を追加する**
- **`python` コマンド単体ではなく `uv run` を使う**

### 品質ゲート

**[現状]** `check_code_quality.sh` が 4 チェックを順に実行: `ruff format` → `ruff check` → `mypy` → `pytest`。

- Python `>=3.13`、ruff `target-version = py313`、line-length 88
- ruff select 17 カテゴリ (E, W, F, I, N, UP, B, A, C4, SIM, ARG, PT, PTH, TCH, RUF, **S** bandit, **PL** pylint)。ignore: COM812, ISC001, PLR0913
- **mypy `strict = true`。`packages = ["src", "tests"]` でテストも型検査対象**。pydantic-mypy の `init_forbid_extra` / `init_typed` / `warn_required_dynamic_aliases` すべて true
- pytest: `asyncio_mode = "auto"`、**`timeout = 10` 秒**、`norecursedirs = ["tests/e2e"]`
- uv: `exclude-newer = "14 days"`。torch/torchaudio は `pytorch-cpu` インデックスから解決

**[現状]** `check_code_quality.sh` は `EXIT_STATUS` を計算しているが**末尾に `exit $EXIT_STATUS` がなく、常に終了コード 0 で終わる**。また `grep -rn "check_code_quality"` がリポジトリ内 0 件で、hook 設定はリポジトリ内に存在しない (`CLAUDE.md:1` は PostToolUse hook でチェックされると述べているため、紐付けはユーザーグローバル設定側にあると推測 — **未確認**)。

### テスト方針

**[現状]** テスト関数総数 192 (うち E2E 25)。ディレクトリはソースの層構造をミラーする。

- unit / integration の明示マーカーやディレクトリ分離はなく、層ごとのディレクトリ分割で暗黙に区分。`tests/presentation/` が実質 integration (Starlette `TestClient` 経由)
- `tests/conftest.py:9-28` — **autouse fixture で `botocore.endpoint.Endpoint.make_request` を monkeypatch し、実 AWS 通信を RuntimeError で強制検出**
- `tests/presentation/conftest.py:14-18` — `client` fixture が `TestClient(create_app())` をテストごとに新規生成。モックは `client.app.state.<dep> = AsyncMock()` で上書き
- モック手段: `unittest.mock` 主体。AWS は `botocore.stub.Stubber` と `moto.mock_aws`、HTTP は `responses.RequestsMock`。**手書きの Fake/Stub クラス定義は 0 件**
- E2E は実サーバープロセスを `subprocess.Popen` で起動 (ポート 18765)。`FileAudioCapture` を `e2e_entrypoint.py` 経由で注入して WAV をマイク入力に差し替える。テスト専用エンドポイント `/api/_test/switch-audio` も存在
- **E2E テストは実クラウド通信・実プロセス起動を伴うため勝手に実行しない。** 一区切りついたタイミングでユーザーに確認を求める (`CLAUDE.md`)

**[現状]** `CLAUDE.md` のテスト観点指示:

- 検証手順には設計ドキュメントとの整合性など設計レベル・統合レベルの観点を含める
- 自明なこと、Pydantic 等の外部ライブラリで保証されている機能 (frozen 検証など) はテスト観点に含めない
- **必ずテストを実装する**

### ドキュメント整合

**[現状]** `design.md` が「Voice Input App - 要件定義 v5」として現行仕様を記述している。本文書の機能を実装する際は `design.md` の更新が必要。

**[現状]** `todo.md` は全 11 行で Phase 1〜9 が全て `[x]` 完了。未着手項目はゼロ。ただしファイル名がクリーンアーキテクチャ移行前の記述 (`sse.py` / `routes.py` / `state.py`) のまま残存しており現構成と一致しない。

**[現状]** ポート 8765 は `settings.py:76` (環境変数で上書き可) と `toggle-recording.sh:6` (ハードコード、`FRAETOR_SERVER_PORT` を参照しない) の 2 箇所に別々に存在する。

---

## 9. 未指定事項の一覧 (実装前に合意が必要)

| # | 機能 | 未指定事項 |
|---|---|---|
| 1 | 機能1 | 無音区切り閾値のデフォルト値 (「2 秒、いや 3 秒とか」で確定していない) |
| 2 | 機能1 | 閾値の設定手段 (環境変数 / UI / 設定ファイル) |
| 3 | 機能1 | 既存 `silence_timeout_sec` (120 秒、自動録音停止) との関係 |
| 4 | 機能1 | 「リクエスト量を下げる」がリクエスト**回数**か音声**データ量**か (分割で回数は増える) |
| 5 | 機能1 | 分割による認識精度低下の許容基準 |
| 6 | 機能2 | エディタライブラリの選定 |
| 7 | 機能2 | React 導入の可否 (許容の表明のみで指定ではない) |
| 8 | 機能2 | ビルドツール選定、Tailwind CDN の扱い |
| 9 | 機能2 | Vim キーバインド設定の永続化先 |
| 10 | 機能2 | 「VS Code のようなエディタ」に含める機能の範囲 |
| 11 | 機能2 | クリップボード共有の方向 (yank→OS / OS→paste / 双方向) |
| 12 | 機能3 | 新設エンドポイントのパスと名前 |
| 13 | 機能3 | 2 回目の呼び出しで送信確定した際に録音を停止するか |
| 14 | 機能3 | 投入コマンド (`agent prompt` = 即実行 / `pane send-text` = 目視後 Enter) |
| 15 | 機能3 | Herdr 送信時に校正完了を待つか、未校正で即送信するか |
| 16 | 機能3 | ペイン ID の生存確認方法 |
| 17 | 機能3 | 「手動送信ボタン」と「セッション選択 UI」が別要素か一体か |
| 18 | 機能3 | Herdr セッション一覧の更新契機 |
| 19 | 機能3 | 送信失敗時のユーザーフィードバック |
| 20 | 機能4 | 翻訳層に使う具体的なモデル |
| 21 | 機能4 | スクリーンショットの撮影間隔 (「何秒かに 1 回」で秒数未確定) |
| 22 | 機能4 | スクリーンショットの撮影対象範囲 (全画面 / ウィンドウ / マルチディスプレイ) |
| 23 | 機能4 | 翻訳層に渡す画像の枚数上限と間引き方針 |
| 24 | 機能4 | マウス位置の取得方法と LLM への渡し方 |
| 25 | 機能4 | 「どこを見ていそうか」の推定に使う情報源 |
| 26 | 機能4 | スクリーンショットの保存・破棄ポリシー (**プライバシー観点の判断が必要**) |
| 27 | 機能4 | 翻訳層を通す / 通さないの切り替え方法 |
| 28 | 機能4 | 翻訳層の出力をユーザーが確認・編集できるか |
| 29 | 機能4 | 翻訳層のタイムアウト値と失敗時の挙動 |
| 30 | 機能4 | 翻訳層と既存の校正機能の関係 |
| 31 | 機能4 | 翻訳層の起動契機 (手動送信ボタン / Herdr トグルのどちらか、両方か) |
| 32 | 機能5 | 判定に使う具体的なモデル |
| 33 | 機能5 | 判定の呼び出し契機 |
| 34 | 機能5 | 「意味なし」判定時のテキストの扱い |
| 35 | 機能5 | 判定の誤りをユーザーが訂正・介入する手段 |
| 36 | 機能5 | ストリーミングモードと他モードの切り替え方法 |
| 37 | 機能5 | ストリーミングモード中の履歴保存・校正の扱い |
| 38 | 機能5 | 送信先 Herdr セッションの決定方法 |
| 39 | 機能5 | 逐次送信でエージェントが飽和した場合の制御 |
| 40 | 機能5 | ストリーミングモードでのセッション時間上限 (現状 10 分) |
| 41 | 機能5 | 判定 LLM の呼び出し頻度と累積コストの許容範囲 |
| 42 | 全体 | 機能1〜4 の相互の実装順序・優先度 (機能5 が最後であることは確定) |

---

## 10. 参考資料

| 資料 | 場所 |
|---|---|
| Fraetor 現行要件定義 | `design.md` |
| Fraetor 開発規約 | `CLAUDE.md` |
| 貼り付け待ち時間 調査レポート (Herdr 一次情報検証済み) | `docs/paste-latency-research.md` **(現在リポジトリに存在せず、検証不能。本文§4.2の要約のみが残っている)** |
| MAI-Transcribe-1 調査 | `docs/mai-transcribe-1-research.md` |
| Gemini 音声ワークアラウンド | `docs/gemini-audio-workaround.md` |
| Herdr 公式サイト | https://herdr.dev |
| Herdr Socket API | https://herdr.dev/docs/socket-api/ |
| Herdr Agent Skill | https://herdr.dev/docs/agent-skill/ |
| Herdr CLI リファレンス | `docs/next/website/src/content/docs/cli-reference.mdx` (herdrdev/herdr) |
| Herdr `SessionSnapshot` 実装 | `src/api/schema/session.rs` (herdrdev/herdr) |
