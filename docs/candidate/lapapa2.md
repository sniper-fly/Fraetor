# VoxPipe: Linux音声入力アプリケーション 実装プラン

## Context

Linuxであらゆるアプリに音声入力可能なデーモンアプリを作成する。F13キー押下中にマウスカーソル付近にポップアップを表示し、Google Cloud Speech-to-Text でリアルタイム音声認識結果を表示する。5秒ごとにGemini Flash Liteで直近の認識テキストを補正し精度を向上させる。キーを離すと最終補正後のテキストをクリップボード経由でアクティブなアプリに貼り付ける。

## 動作フロー

```
F13押下 → ポップアップ表示 → 録音開始 → リアルタイムSTT表示
  ↕ 5秒ごとにGemini補正（直近5秒分を置換）
F13解放 → 録音停止 → 最終補正 → クリップボードコピー → Ctrl+V → ポップアップ非表示
```

## 技術スタック

| 要素 | 選定 | 理由 |
|------|------|------|
| 言語 | Python 3.12+ | ライブラリが豊富、ユーザー希望 |
| パッケージ管理 | uv | ユーザーの既存プロジェクト(lapapa)と統一 |
| 音声キャプチャ | sounddevice | lapapa実績あり、int16直接出力 |
| STT | google-cloud-speech (streaming) | GC経由、interim_results対応 |
| 補正 | google-genai (Vertex AI + ADC) | 既存ADC認証を共有 |
| GUI | PyQt6 | フォーカス非奪取が可能、リッチテキスト対応 |
| ホットキー | pynput | X11でのグローバルキー検出が簡単 |
| クリップボード | xclip (subprocess) | システムに既にインストール済み |
| キーシミュレーション | xdotool (subprocess) | システムに既にインストール済み |

## プロジェクト構成

```
/home/user/Public/voxpipe/
├── pyproject.toml
├── .python-version          # 3.12
├── .gitignore
├── src/
│   └── voxpipe/
│       ├── __init__.py
│       ├── main.py          # エントリーポイント、セッションライフサイクル管理
│       ├── hotkey.py         # pynput F13リスナー → Qt signal
│       ├── audio.py          # sounddevice → queue.Queue ベースの音声ストリーミング
│       ├── stt.py            # Google Cloud STT streaming_recognize ワーカー
│       ├── corrector.py      # Gemini補正（5秒タイマー + スレッドプール）
│       ├── segments.py       # テキストセグメント管理（corrected/uncorrected/interim）
│       ├── popup.py          # PyQt6フレームレスオーバーレイ
│       └── clipboard.py      # xclip + xdotool によるペースト
```

## スレッドモデル

| スレッド | 担当 | 同期機構 |
|----------|------|----------|
| Mainスレッド | Qt event loop、ポップアップ描画、QTimerコールバック | - |
| pynputスレッド | F13キーイベント監視 | Qt signal (queued connection) |
| PortAudioコールバック | 音声チャンクをキューに投入 | queue.Queue |
| STTワーカースレッド | streaming_recognize実行 | queue.Queue → Qt signal |
| 補正ワーカースレッド | Gemini API呼び出し | threading.Lock (SegmentManager) |

## モジュール詳細設計

### 1. `config.py` - 設定
- `AppConfig` dataclass: sample_rate=16000, channels=1, chunk=100ms, correction_interval=5.0s
- Geminiモデル名は環境変数 `VOXPIPE_GEMINI_MODEL` で設定可能（デフォルト: 設定可能）
- Vertex AI: プロジェクトID/ロケーションは環境変数 or `~/.config/voxpipe/config.toml`
- Google Cloud ADC で STT と Gemini 両方の認証をカバー

### 2. `hotkey.py` - F13キーリスナー
- `pynput.keyboard.Listener` をデーモンスレッドで実行
- F13検出: `keyboard.Key.f13` または `KeyCode(vk=191)` の両方チェック
- `_is_held` フラグでキーリピート防止（最初のpressのみ反応）
- マウス位置は `xdotool getmouselocation` で取得
- `HotkeySignals(QObject)`: `key_pressed(int, int)`, `key_released()` シグナル

### 3. `audio.py` - 音声キャプチャ
- `sounddevice.InputStream(dtype="int16", blocksize=1600)` → LINEAR16直接出力
- コールバックで `queue.Queue(maxsize=300)` に投入（30秒分バッファ）
- `audio_generator()`: ブロッキングジェネレータ、`None` センチネルで終了
- lapapa同様の100msチャンクサイズ

### 4. `stt.py` - Speech-to-Text ストリーミング
- `QRunnable` + `QThreadPool` でワーカースレッド実行
- `speech.SpeechClient().streaming_recognize()` にリクエストジェネレータを渡す
- 最初のリクエスト: `StreamingRecognitionConfig`（config + interim_results=True）
- 以降: 音声チャンクの `StreamingRecognizeRequest`
- `language_code="ja-JP"`, `alternative_language_codes=["en-US"]`
- `enable_automatic_punctuation=True`
- シグナル: `interim_result(str, float)`, `final_result(str, float, float)`, `error(str)`

### 5. `segments.py` - テキストセグメント管理
- `TextSegment` dataclass: text, start_time, end_time, is_corrected
- `SegmentManager`: スレッドセーフ（threading.Lock）
  - `add_final_segment()`: STT final result追加
  - `update_interim()`: 最新のinterimテキスト更新
  - `get_segments_in_window(5.0)`: 直近5秒の未補正セグメント取得
  - `apply_correction()`: 指定セグメント範囲を補正済みセグメントに置換
  - `get_display_text() → (corrected, uncorrected, interim)`: 3ゾーン表示用
  - `get_full_text()`: 最終テキスト（interim除く）
- 日本語テキスト結合は `"".join()` （スペースなし）

### 6. `corrector.py` - Gemini補正
- `QTimer` で5秒ごとにメインスレッドでトリガー
- `_correction_in_flight` フラグで重複防止（前の補正が未完了ならスキップ）
- `QThreadPool(maxThreadCount=1)` で補正ワーカーをシリアル実行
- Gemini初期化: `genai.Client(vertexai=True, project=..., location=...)`
- 補正プロンプト（日本語）:
  ```
  音声認識テキストの校正アシスタントとして、誤認識や不自然な表現を修正。
  元の意味を変えない。句読点を適切に補正。修正後テキストのみ出力。
  ```
- F13解放時: `do_final_correction()` で全未補正セグメントをブロッキング補正

### 7. `popup.py` - ポップアップUI
- フォーカス非奪取のためのWindowFlags:
  ```python
  FramelessWindowHint | WindowStaysOnTopHint | Tool |
  WindowDoesNotAcceptFocus | X11BypassWindowManagerHint
  ```
- `setAttribute(WA_ShowWithoutActivating)` 必須
- `WA_TranslucentBackground` で半透明ダーク背景
- `QTextEdit` (読み取り専用)でHTML表示:
  - 補正済み: 白色テキスト
  - 未補正: 薄黄色テキスト  
  - interim: グレーイタリック
- スクリーン端での位置調整（画面外はみ出し防止）
- 100ms間隔の `QTimer` でUI更新

### 8. `clipboard.py` - クリップボード+ペースト
- `xclip -selection clipboard` でクリップボードにコピー（subprocess.Popen + stdin pipe）
- 50ms待機後 `xdotool key --clearmodifiers ctrl+v` でペースト
- `--clearmodifiers` でF13等の修飾キー干渉を防止

### 9. `main.py` - オーケストレーター
- `VoiceInputSession`: 1回のpress-release セッションを管理
  - `start(mouse_x, mouse_y)`: 全コンポーネント起動
  - `stop()`: 停止シーケンス（下記参照）
- `VoxPipeApp`: QApplication + HotkeyListener のワイヤリング
  - `setQuitOnLastWindowClosed(False)` でポップアップ非表示時もデーモン継続
- 停止シーケンス:
  1. 補正タイマー停止
  2. 音声キャプチャ停止（Noneセンチネル送出 → STTジェネレータ終了）
  3. STTワーカー停止要求
  4. 200ms待機（バッファ処理完了待ち）
  5. 最終Gemini補正（ブロッキング）
  6. `get_full_text()` → xclip → xdotool
  7. ポップアップ非表示

## エラーハンドリング

| シナリオ | 対処 |
|----------|------|
| マイク未接続 | PortAudioError catch → デスクトップ通知 |
| STT認証失敗 | error signal → ログ出力、セッション継続 |
| STT 305秒制限 | OutOfRange → 蓄積テキスト保持、finishedシグナル |
| Gemini API失敗 | 未補正テキストをそのまま使用 |
| Gemini応答遅延 | in_flightフラグでスキップ、次回に拡大ウィンドウで補正 |
| xclip/xdotool失敗 | デスクトップ通知でテキスト表示 |

## 依存パッケージ (pyproject.toml)

```toml
dependencies = [
    "google-cloud-speech>=2.27.0",
    "google-genai>=1.0.0",
    "sounddevice>=0.5.1",
    "numpy>=2.0.0",
    "PyQt6>=6.7.0",
    "pynput>=1.7.7",
]
```

## 実装順序

1. **Phase 1**: プロジェクト基盤 (`uv init`, `config.py`, `audio.py`, `segments.py`)
2. **Phase 2**: STT統合 (`stt.py`) - マイク→コンソール出力で動作確認
3. **Phase 3**: ポップアップUI (`popup.py`) - STT結果の画面表示
4. **Phase 4**: ホットキー (`hotkey.py`) - F13でセッション開始/停止
5. **Phase 5**: Gemini補正 (`corrector.py`) - 5秒ごとの補正動作確認
6. **Phase 6**: クリップボード入力 (`clipboard.py`) - E2Eテスト
7. **Phase 7**: エラーハンドリング、グレースフルシャットダウン

## 検証方法

1. `uv run voxpipe` で起動、F13押下でポップアップ表示確認
2. 日本語で話しかけ、リアルタイムにテキストが表示されることを確認
3. 5秒以上話し、Gemini補正で薄黄色テキストが白色に変わることを確認
4. F13解放後、テキストエディタにテキストが貼り付けられることを確認
5. 複数回のpress-releaseサイクルが正常に動作することを確認

## 注意事項

- F13キーが検出されない場合: `xev` コマンドでキーコードを確認し設定で変更可能に
- Geminiモデル名は環境変数で変更可能にする（将来のモデル更新に対応）
- Vertex AI のプロジェクトID/ロケーションは初回起動時に設定が必要
