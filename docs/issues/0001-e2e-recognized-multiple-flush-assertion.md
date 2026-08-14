# 0001: E2Eで逐次flushの複数回発火を検証していない

## 現状

`tests/e2e/test_mic_and_vad.py:76-91` の `test_multiple_utterances_with_short_pause_stay_in_one_session` は
録音継続の有無(`status_events == [True, False]`)のみを検証している。`recognized` イベントが
実際に複数回発火したかは `_print_recognized("02_multiple_utterances.wav", events)` で表示するだけで、
assertion が存在しない。

## 課題

phase3 で実装した「無音区切りごとの逐次flush」機能の中核動作(1セッション内で `recognized` が
複数回発火する)が、E2Eレベルで保証されていない。ユニット/アプリケーション層
(`tests/dictation/application/test_recording_session_service.py::test_flushed_segments_are_appended_in_order_during_recording`)
では複数回配信そのものは検証済みだが、実音声・実STTを通す経路(E2E)は未検証のまま。

なお `tests/e2e/fixtures/audio/02_multiple_utterances.wav` は `.gitignore` で追跡除外されており、
CIでは自動実行されず開発者が手元で録音した場合のみ実行される。

## 検討したい対応案

1. 既存テストに `recognized` イベントが2件以上届くことを検証する assertion を1行追加する
2. 別テストとして新設し、既存テストの責務(録音継続)とは分離する
3. 実機マイクで3秒無音を挟んだ発話を行い、目視確認の証跡を一度残す

## 背景

2026-08-11 のセッションで、ユーザーからの「つまりE2Eテストはもう通っていて今回の逐次音声認識は
もう実用可能な状態になっているということですね?」という確認質問に答える過程で、AI自身が
「逐次flushが実クラウドで動作していることを確認した」という前の報告の根拠が実際には
HTTPステータスの間接指標だけであり、複数回発火そのものは検証していなかったと判明した。
