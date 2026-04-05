# Gemini Live API AUDIO モードワークアラウンド

## 背景

`gemini-3.1-flash-live-preview` は `response_modalities=[TEXT]` をサポートしておらず、
接続時に WebSocket 1011 エラーが発生する。
このため AUDIO モードで接続し、`output_audio_transcription` 経由でテキスト応答を取得している。

## 修正が必要なファイルと箇所

### `src/correction.py`

#### 1. `connect()` — LiveConnectConfig (L39-41)

```python
# 現在 (ワークアラウンド)
config = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    output_audio_transcription=types.AudioTranscriptionConfig(),
    ...
)

# 修正後
config = types.LiveConnectConfig(
    response_modalities=[types.Modality.TEXT],
    ...
)
```

- `response_modalities` を `AUDIO` → `TEXT` に変更
- `output_audio_transcription` の行を削除

#### 2. `correct()` — レスポンス解析 (L64-67)

```python
# 現在 (ワークアラウンド)
async for message in self._session.receive():
    sc = message.server_content
    if sc and sc.output_transcription and sc.output_transcription.text:
        corrected_parts.append(sc.output_transcription.text)

# 修正後
async for message in self._session.receive():
    if message.text is not None:
        corrected_parts.append(message.text)
```

### `tests/test_correction.py`

#### 3. `_make_message()` — モック構造 (L14-24)

```python
# 現在 (ワークアラウンド)
def _make_message(text: str | None) -> MagicMock:
    transcription = MagicMock()
    transcription.text = text
    server_content = MagicMock()
    server_content.output_transcription = transcription
    msg = MagicMock()
    msg.server_content = server_content
    return msg

# 修正後
def _make_message(text: str | None) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    return msg
```

## 確認方法

TEXT モードが使えるようになったかは、以下で確認できる:

```python
config = types.LiveConnectConfig(
    response_modalities=[types.Modality.TEXT],
    ...
)
# 接続時に 1011 エラーが出なければ修正済み
```
