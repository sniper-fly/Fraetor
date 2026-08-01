# MAI-Transcribe-1 調査レポート

調査日: 2026-05-09

## 1. 調査目的

現行 Fraetor は Azure Speech Services の Continuous Recognition (`azure-cognitiveservices-speech` SDK) を用いて日本語のリアルタイム文字起こしを行っている。Microsoft が新たに公開した `MAI-Transcribe-1` を採用することで、より高精度な認識結果を得られるかを検証する。本ドキュメントは公式情報源(microsoft.ai / techcommunity.microsoft.com / learn.microsoft.com)のみを根拠に、実装に必要な情報を整理する。

---

## 2. ⚠️ 重要な結論 (先に提示)

**現状の MAI-Transcribe-1 を Fraetor にそのまま導入することはできない。** 以下の3点が現行アーキテクチャと根本的に不整合のため。

| 項目 | 現行 Fraetor | MAI-Transcribe-1 (2026-04 時点) |
|---|---|---|
| 認識モード | リアルタイム (Continuous Recognition) | **バッチのみ** (リアルタイム未対応) |
| リージョン | `japaneast` | **East US / West US のみ** |
| 音声入力 | PCM ストリーム (PushAudioInputStream) | ファイル (WAV/MP3/FLAC, 70MB 以内) |

公式モデルカードに「Real-time transcription, diarization, and context biasing aren't supported yet; these capabilities are planned for an upcoming release.」と明記されている。

採用したい場合の現実的な選択肢は §8 を参照。

---

## 3. モデル概要

- 開発元: Microsoft AI Superintelligence チーム
- 公開: 2026-04-02 (Public Preview, SLA なし)
- 価格: **$0.36 / 音声1時間**
- アーキテクチャ: Autoregressive モデル (テキスト予測型, multimodal model 系列)
- 対応言語数: 25 (日本語含む。後述)
- アクセス手段:
  - Azure Speech (LLM Speech API の `enhancedMode.model` パラメータ経由)
  - Voice Live API の `input_audio_transcription` でも利用可
  - MAI Playground (試用)

### 対応言語と日本語コード

`Arabic / Chinese / Czech / Danish / Dutch / English / Finnish / French / German / Hindi / Hungarian / Indonesian / Italian / **Japanese** / Korean / Norwegian Bokmål / Polish / Portuguese / Romanian / Russian / Spanish / Swedish / Thai / Turkish / Vietnamese`

`locales` パラメータで日本語を強制指定する場合は **`ja`** (note: 現行 Fraetor は Azure SDK で `ja-JP` 指定 → API 仕様が異なる点に注意)。指定省略時は自動言語判定。

---

## 4. 精度ベンチマーク (FLEURS / WER, lower is better)

公式モデルカードからの抜粋。Fraetor の関心がある日本語と、対応モデルの平均値を中心に整理。

| Model | 日本語 (JA) | 平均 (AVG) |
|---|---|---|
| **MAI-Transcribe-1** | **1.9 %** | **3.86 %** |
| Scribe v2 | 2.3 % | 4.32 % |
| GPT-Transcribe | 2.8 % | 4.17 % |
| Gemini 3.1 Flash | 3.9 % | 4.89 % |
| Whisper-large-v3 | 5.3 % | 7.60 % |

**勝率**: MAI-Transcribe-1 は Whisper に対し 25/25 言語勝利、Gemini 3.1 Flash に 22/25、GPT-Transcribe に 15/25、Scribe v2 に 15/25 で勝利。

注意: 現行 Fraetor が利用している Azure Speech (Fast/Continuous) のスコアは公式比較表に含まれていないため、直接の優位性は本データのみでは断定できない。

---

## 5. 機能対応表 (Fast Transcription / LLM Speech / MAI-Transcribe 比較)

公式 LLM Speech ドキュメントの表より。

| 機能 | Fast transcription (既定) | LLM Speech (enhanced) | MAI-Transcribe-1 |
|---|---|---|---|
| Transcription | ✅ | ✅ | ✅ |
| Translation | ❌ | ✅ | ❌ |
| Diarization | ✅ | ✅ | ❌ |
| Channel (stereo) | ✅ | ✅ | ✅ |
| Profanity filtering | ✅ | ✅ | ✅ |
| ロケール指定 (`locales`) | ✅ | ❌ | ✅ |
| Custom prompting | ❌ | ✅ | ❌ |
| Phrase list | ✅ | ❌ | ❌ |

---

## 6. 入出力仕様

### 入力
- フォーマット: `WAV` / `MP3` / `FLAC`
- 最大ファイルサイズ: **70 MB** (MAI-Transcribe-1 利用時の独自制限。LLM Speech の通常上限 500MB より厳しい)
- 最大長: LLM Speech 全体としては 5 時間以内、ただし上記 70MB の制約が支配的

### 出力 (JSON)
```json
{
  "durationMilliseconds": 4000,
  "combinedPhrases": [
    { "text": "認識結果がここに入る" }
  ],
  "phrases": [
    {
      "offsetMilliseconds": 80,
      "durationMilliseconds": 6960,
      "text": "...",
      "words": [
        { "text": "with", "offsetMilliseconds": 80, "durationMilliseconds": 160 }
      ],
      "locale": "ja-jp",
      "confidence": 0
    }
  ]
}
```

注意: `confidence` は常に `0` で返る (利用不可)。

---

## 7. 実装方法 (公式コードサンプル)

### 7.1 REST API (curl) — 最小例

```bash
curl --location 'https://<YourServiceRegion>.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15' \
  --header 'Content-Type: multipart/form-data' \
  --header 'Ocp-Apim-Subscription-Key: <YourSpeechResourceKey>' \
  --form 'audio=@"YourAudioFile.wav"' \
  --form 'definition={
    "locales": ["ja"],
    "enhancedMode": {
      "enabled": true,
      "model": "mai-transcribe-1"
    }
  }'
```

ポイント:
- `api-version=2025-10-15`
- エンドポイントは `<region>.api.cognitive.microsoft.com`
- `Ocp-Apim-Subscription-Key` ヘッダ (キー認証) または `Authorization: Bearer <token>` (Microsoft Entra ID, 推奨)
- `definition` は **multipart の文字列フィールド (JSON 文字列)**
- `locales: ["ja"]` を渡すと日本語固定 (省略時は自動判定)

### 7.2 Python SDK (新パッケージ `azure-ai-transcription`)

参考リンク:
- パッケージ: https://pypi.org/project/azure-ai-transcription/
- リファレンス: https://learn.microsoft.com/en-us/python/api/overview/azure/ai-transcription-readme
- GitHub サンプル: https://github.com/Azure/azure-sdk-for-python/tree/azure-ai-transcription_1.0.0b2/sdk/cognitiveservices/azure-ai-transcription/samples

**重要**: 現行 Fraetor が使う `azure-cognitiveservices-speech` (Speech SDK) とは別パッケージ。MAI-Transcribe-1 を使うには新たに `azure-ai-transcription` (preview) を追加導入する必要がある。

```python
import os
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import (
    TranscriptionContent,
    TranscriptionOptions,
    EnhancedModeProperties,
)

endpoint = os.environ["AZURE_SPEECH_ENDPOINT"]
api_key = os.environ["AZURE_SPEECH_API_KEY"]
credential = AzureKeyCredential(api_key)

client = TranscriptionClient(endpoint=endpoint, credential=credential)

with open("audio.wav", "rb") as audio_file:
    enhanced_mode = EnhancedModeProperties(
        task="transcribe",
        # MAI-Transcribe-1 を使う場合は model を指定
        # ※ Python SDK の EnhancedModeProperties での model 指定方法は
        #    リファレンスを確認 (REST 仕様では "model": "mai-transcribe-1")
    )
    options = TranscriptionOptions(enhanced_mode=enhanced_mode)
    request_content = TranscriptionContent(definition=options, audio=audio_file)
    result = client.transcribe(request_content)
    print(result.combined_phrases[0].text)
    for phrase in result.phrases:
        print(f"[{phrase.offset_milliseconds}ms]: {phrase.text}")
```

依存追加 (CLAUDE.md 規約に従い `uv add` を使用):

```bash
uv add azure-ai-transcription
uv add azure-identity   # Microsoft Entra ID 認証時 (推奨)
```

環境変数:
```bash
export AZURE_SPEECH_ENDPOINT="https://<resource>.cognitiveservices.azure.com"
export AZURE_SPEECH_API_KEY="<your-api-key>"
```

### 7.3 認証方式

| 方式 | 用途 | 設定 |
|---|---|---|
| API Key | 開発・PoC | `Ocp-Apim-Subscription-Key` ヘッダ / `AzureKeyCredential` |
| Microsoft Entra ID (推奨) | 本番 | `DefaultAzureCredential` + `Cognitive Services User` ロール付与 |

### 7.4 リトライ戦略 (公式推奨)

- 最大 5 回、指数バックオフ (2 → 4 → 8 → 16 → 32 秒、合計 62 秒)
- リトライすべきエラー: HTTP 429 / 500 / 502 / 503 / 504、`ServiceRequestError`、`ServiceResponseError`、`ConnectionError` / `TimeoutError` / `OSError`、`status_code=None` (不完全レスポンス)
- リトライしてはいけない: HTTP 400 / 401 / 422 などのクライアントエラー
- リトライ前に `audio_file.seek(0)` でストリームをリセット
- 並列実行時はデフォルトの 300 秒 read timeout を超える可能性に注意

---

## 8. 現行 Fraetor への適用評価

### 8.1 現行アーキテクチャとのギャップ

| 観点 | 現状 | MAI-Transcribe-1 の制約 |
|---|---|---|
| ストリーミング | sounddevice → PushAudioInputStream → recognizing/recognized イベント | バッチのみ。WAV/MP3/FLAC ファイル送信が必要 |
| UI 中間結果 (interim) | `recognizing` で逐次表示 (グレー) | 取得不可 (リアルタイム未対応) |
| 確定セグメント | `recognized` で文単位 | 1 リクエスト = 1 ファイル全体の transcript。文単位は `phrases[]` から自前で組み立て |
| リージョン | `japaneast` | East US / West US のみ |
| 認証情報 | SSM Parameter Store から SDK 用キー取得 | LLM Speech 用エンドポイント + キー (別 Foundry リソースが必要な可能性が高い) |
| 依存ライブラリ | `azure-cognitiveservices-speech` | `azure-ai-transcription` (新パッケージ・preview) を追加 |

### 8.2 採用パターンの選択肢

#### パターン A: そのまま置き換え (非推奨・現状不可)
リアルタイムインタラクション(録音中の interim 表示)を犠牲にすれば可能。録音停止 → ファイル化 → MAI-Transcribe-1 投入 → 結果表示の一括フローになる。
- 設計書 §1.3 の interim/recognized 二段階表示が機能しなくなり、UX が大きく変わる
- セッション最大 3 分なので 1 ファイルあたり概ね 5–10MB 程度 (16kHz/16bit/mono なら 3 分で約 5.5MB) で 70MB 上限は問題なし

#### パターン B: ハイブリッド (現実的・推奨検討)
- 録音中: 既存 Azure STT Streaming で interim/recognized を表示 (現行 UX 維持)
- 録音停止後: 録音 PCM を WAV 化し、MAI-Transcribe-1 にバッチ投入 → 高精度の最終確定テキストとして上書き
- 既存の校正パイプライン (Gemini) の前段に挟む形になる
- コスト: $0.36/h × セッション総時間 (3分なら約 $0.018/セッション)

#### パターン C: 待機
real-time / diarization / context biasing は「upcoming release」で予定されている。それらが GA したタイミングで再評価する。

### 8.3 設計ドキュメント (`docs/azure-stt-only-spec.md`) との整合性

- §1.1〜1.6 の Continuous Recognition 前提のフロー (PushAudioInputStream / recognizing / recognized) は MAI-Transcribe-1 では成立しない
- §5 のデータフロー、§6 の Segment モデル、§9 のセッションライフサイクルはストリーミング前提のため、パターン A 採用時には大幅な再設計が必要
- パターン B なら既存の `AzureSttClient` (`src/stt.py`) を維持しつつ、`session_manager.py` の停止フローに「MAI による再書き起こし」ステップを追加するだけで済む可能性が高い

---

## 9. 未確認事項 / 追加で要確認

実装に着手する前に、以下を公式ドキュメントもしくは実機で確認する必要がある。

1. **`azure-ai-transcription` Python SDK で `mai-transcribe-1` model をどう指定するか**
   公式サンプルコード本文には REST 例しかない。`EnhancedModeProperties` クラスのパラメータに `model` 指定があるかは PyPI / GitHub サンプルの確認が必須。
2. **既存 Azure リソースでそのまま使えるか**
   現行 SSM 経由で取得しているキーが `japaneast` の Speech リソースのものなので、East US/West US の Foundry リソースを別途作成する必要がある。
3. **出力テキストの正規化**
   MAI-Transcribe-1 はデフォルトで「display format」(句読点・大文字化等を含む) で返る模様。Fraetor の表示に合わせて lexical / display どちらを採用するか要決定。MAI-Transcribe-1 では prompt-tuning が不可のため、後段で整形する必要がある。
4. **Voice Live API ルート**
   ストリーミング用途なら Voice Live API の `input_audio_transcription` で MAI-Transcribe-1 を指定する経路も存在する。これがリアルタイム interim を返すか、本研究では未確認。

---

## 10. 参考資料 (一次情報)

- 公式アナウンス (Microsoft AI): https://microsoft.ai/news/state-of-the-art-speech-recognition-with-mai-transcribe-1/
- モデルカード (PDF): https://microsoft.ai/pdf/MAI-Transcribe-1-Model-Card.pdf
- Foundry モデルカタログ: https://ai.azure.com/catalog/models/MAI-Transcribe-1
- Foundry Labs プロジェクトページ: https://labs.ai.azure.com/projects/mai-transcribe-1/
- Microsoft Learn (MAI-Transcribe-1 in LLM Speech API): https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe
- Microsoft Learn (LLM Speech API 全体): https://learn.microsoft.com/en-us/azure/ai-services/speech-service/llm-speech
- Python SDK パッケージ: https://pypi.org/project/azure-ai-transcription/
- Python SDK リファレンス: https://learn.microsoft.com/en-us/python/api/overview/azure/ai-transcription-readme
- Python SDK サンプル: https://github.com/Azure/azure-sdk-for-python/tree/azure-ai-transcription_1.0.0b2/sdk/cognitiveservices/azure-ai-transcription/samples
- Tech Community 発表記事: https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-mai-transcribe-1-mai-voice-1-and-mai-image-2-in-microsoft-foundry/4507787
