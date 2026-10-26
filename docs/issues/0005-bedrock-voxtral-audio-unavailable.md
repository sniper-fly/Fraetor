# 0005: Bedrock Voxtral が音声入力を受け付けない(保留)

## 現状

STT として Bedrock の Voxtral(`mistral.voxtral-small-24b-2507` / `mistral.voxtral-mini-3b-2507`)を
選べるようにする依頼だったが、**音声入力が使えないため実装を見送った**。`stt.engine` の選択肢にも載せていない
(選べるのに動かない状態を作らないため)。代わりに Vertex の `gemini-3.5-transcribe` を追加した。

## 確認した条件

`dmm_ai` アカウントのみで実施(SSOアカウントでのAI呼び出しはしていない)。

- 形式: AWS公式サンプル(`aws-samples/mistral-on-aws` の `Voxtral_Bedrock.ipynb`)と同じ
  `invoke_model` + `input_audio {data(base64), format: "wav"}`
- 範囲: 9リージョン × mini / small の全組み合わせ
- 結果: **テキストは成功し、音声パートだけが `Model does not support audio modality` で失敗**。
  サンプリングレート・format値・長さを変えても同じ
- 公式が通ると報告する `eu-west-2` / `ap-northeast-1` でも失敗(同リポジトリ issue #409 / PR #412 は2026-10-21の測定)
- Mistral公式形式(`input_audio` に文字列)は形式不正で拒否。`file` 型は黙って無視される
  (`prompt_tokens` がテキストのみと同一で、音声は処理されていない)

## 公式サンプルの制約

- リクエストは約2MB(約45秒)まで。Converse API は非対応
- **対応言語に日本語がない**。日本語口述の用途に合わない可能性が高い
- モデルカードは Legacy、EOL 2027-03-30

## 再確認の手順

1. `dmm_ai` のキーで、`invoke_model` に `input_audio {data, format: "wav"}` を含むリクエストを送る
   (短い日本語WAV、`tests/e2e/fixtures/audio/04_short_utterance.wav` 等)
2. 「音声パートが処理された」ことは、同じテキストのみのリクエストと `prompt_tokens` を比べて確かめる
   (無音や正弦波では判別できない)
3. 通るようになった場合は、ライブラリ(fraetor-dictation)に `SttEngineSpecPort` の実装を足す
   (`GeminiEngineSpec` が雛形)。日本語の認識品質を先に確認すること
