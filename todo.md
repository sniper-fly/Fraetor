# Fraetor 実装 TODO

## 機能1: 無音区間による逐次文字起こし + 動的設定画面

プラン: `.claude/plans/docs-requirements-md-scalable-stallman.md`

### phase1: 動的設定の基盤 (DynamicSettings + リポジトリ)
目的: 実行中に読み書きできる設定の置き場所を新設する。`Settings` からのフィールド削除と消費側の移行は phase2 で行うため、このフェーズでは値の定義が二重化した状態を許容する (既存コードは一切変更しない)。

- [x] `src/shared/config/dynamic_settings.py`  # DynamicSettings (frozen, segment_silence_sec < silence_timeout_sec のバリデータ)
- [x] `tests/shared/config/test_dynamic_settings.py`  # 上記に対応する単体テスト
- [x] `src/shared/config/ports.py`  # SettingsRepositoryPort (get / update)
- [x] `src/shared/config/jsonc_settings_repository.py`  # JSONC 読み書き、不在時の雛形生成、パース失敗時の既定値フォールバック
- [x] `tests/shared/config/test_jsonc_settings_repository.py`  # 上記に対応する単体テスト
- [x] `uv add json5` で JSONC パース用の依存を追加する

### phase2: 消費側の settings_repository 経由化と DI 再配線
目的: 動的化対象の値を `Settings` から削除し、全消費箇所を「利用する瞬間に `get()` を読む」形へ移行する。このフェーズ完了時点で「次回利用時に反映」が成立する。逐次 flush 用の `segment_silence_sec` の消費は phase3 で追加する。

- [x] `src/shared/config/settings.py`  # 動的化対象フィールドの削除 (除外項目は残す)
- [x] `tests/shared/config/test_settings.py`  # 削除に追随
- [x] `src/dictation/infrastructure/vad/factory.py`  # create_vad を新設し vad_threshold を遅延読み込み
- [x] `tests/dictation/infrastructure/vad/test_factory.py`  # 上記に対応する単体テスト
- [x] `src/dictation/infrastructure/stt/factory.py`  # settings_repository を受け取る signature へ変更
- [x] `tests/dictation/infrastructure/stt/test_factory.py`  # 上記に対応する単体テスト
- [x] `src/dictation/application/recording_session_service.py`  # start_session 実行時に get()
- [x] `tests/dictation/application/test_recording_session_service.py`  # 「次回反映」の検証を追加
- [x] `src/proofreading/application/proofread_text_use_case.py`  # execute 実行時に get()
- [x] `tests/proofreading/application/test_proofread_text_use_case.py`  # 「次回反映」の検証を追加
- [x] `src/presentation/routes/shutdown_routes.py`  # リクエスト時に shutdown_delay_sec を読む
- [x] `tests/presentation/routes/test_shutdown_routes.py`  # 上記に追随
- [x] `src/presentation/routes/recording_routes.py`  # SSE 接続時に sse_keepalive_sec を読む
- [x] `tests/presentation/routes/test_recording_routes.py`  # 上記に追随
- [x] `src/presentation/app.py`  # lifespan で app.state.settings_repository を設定
- [x] `src/containers.py`  # settings_repository の Singleton 追加と各 provider の配線変更
- [x] `tests/test_containers.py`  # 配線変更に追随
- [x] `tests/fakes.py`  # InMemorySettingsRepository (プラン外。複数テストで port のフェイクを共用するため新設)
- [x] `tests/conftest.py`  # プラン外。history_dir を tmp_path へ隔離 (settings.jsonc が実ホームに書かれるのを防ぐ)
- [x] `tests/e2e/conftest.py`  # プラン外。タイムアウト短縮を環境変数から settings.jsonc 事前書き出しへ移行

### phase3: 無音区切りによる逐次 flush
目的: VAD の発話開始位置公開から STT の部分送信、無音監視タイマー、コーディネータ統合までを一続きで実装する。`SegmentAccumulator` / SSE / フロントエンドは変更しない (プラン §5 の通り、既存経路がそのまま機能することを既存テストで担保する)。

- [x] `src/dictation/domain/ports.py`  # last_speech_start_sample プロパティと SttEnginePort.flush を追加
- [x] `src/dictation/infrastructure/vad/silero_vad_detector.py`  # VADIterator の start を保持
- [x] `tests/dictation/infrastructure/vad/test_silero_vad_detector.py`  # 上記に対応する単体テスト
- [x] `src/dictation/infrastructure/stt/mai_transcribe_client.py`  # 累積バッファ + 送信済みオフセット方式へ書き換え、flush 実装、stop の最終区間処理
- [x] `tests/dictation/infrastructure/stt/test_mai_transcribe_client.py`  # オフセット追随・trim・no-op ガード・例外非伝播の検証
- [x] `src/dictation/application/segment_silence_monitor.py`  # 残り時間だけ寝る監視ループ (重複呼び出しは許容)
- [x] `tests/dictation/application/test_segment_silence_monitor.py`  # 上記に対応する単体テスト
- [x] `src/dictation/application/audio_pipeline_coordinator.py`  # SegmentSilenceMonitor 組み込みと asyncio.Lock による flush 直列化
- [x] `tests/dictation/application/test_audio_pipeline_coordinator.py`  # 起動/停止・flush 引数・直列化の検証
- [x] `src/containers.py`  # audio_pipeline_coordinator への segment_silence_sec 経路を配線
- [x] `tests/test_containers.py`  # 配線変更に追随
- [x] `tests/dictation/application/test_recording_session_service.py`  # プラン外。§5「追記経路は変更不要」が flush 由来イベントでも成立することの統合検証

プラン (§4.1) からの逸脱: `stop()` は監視停止の前に `_flush_lock` を取得し、進行中の
flush の完了を待つ。プラン通りに `monitor.stop()` を先に呼ぶと、送信中の flush が
`CancelledError` で中断され、STT の送信済みオフセットだけが進んでその区間のテキストが
失われる (`await` 中のタスクキャンセルは shield なしでは即座に伝播する)。

### phase4: 設定 API・設定画面・ドキュメント整合
目的: 動的設定をブラウザから編集できるようにし、設計ドキュメントを実装に追随させる。

- [x] `src/presentation/routes/settings_routes.py`  # GET / PUT /api/settings (DynamicSettings を直接 I/O モデルに使う)
- [x] `tests/presentation/routes/test_settings_routes.py`  # 取得・更新の反映・不正値で 422 の検証
- [x] `src/presentation/app.py`  # settings_routes の router 登録
- [x] `src/templates/index.html`  # 「設定」タブ追加、switchTab の3値対応、loadSettings / saveSettings
- [x] `tests/presentation/routes/test_page_routes.py`  # プラン外。JS の SETTINGS_FIELDS / TABS が DynamicSettings と DOM に一致することの検証
- [x] `design.md`  # 定数章・VAD 章・データフロー章の更新と「動的設定」章・「逐次文字起こし」章の新設
- [x] 実装完了後、E2E テスト (特に `tests/e2e/test_mic_and_vad.py` / `test_mai_transcribe.py`) の実行可否をユーザーに確認する
- [x] `tests/e2e/test_mic_and_vad.py`  # プラン外。既存の recognized>=1 の検証では「逐次分割そのもの」を証明できていなかったため、
      同一セッション内で複数 recognized (segment_id 連番) が届くことを検証するテストを追加した
- [x] `tests/e2e/conftest.py`  # プラン外。`fraetor_server_with_audio` の型を `Callable[..., str]` に修正 (kwargs 渡しが型的に矛盾していた)
- [ ] 3秒以上の無音を挟んだ発話で逐次追記されること・リードタイム短縮を実機で手動確認する

プラン (§7.1) からの逸脱: `PUT /api/settings` はボディを型付きパラメータ
(`body: DynamicSettings`) で受ける。プラン通りハンドラ内で `model_validate()` を
呼ぶと `ValidationError` が FastAPI に捕捉されず 500 になり、「不正値で 422」という
要件を満たせない (ミューテーションテストで確認済み)。

プラン外の判断: 設定項目一覧はJS側の `SETTINGS_FIELDS` とサーバー側の
`DynamicSettings` で二重に持つことになる。片方だけ増減すると「入力欄がない項目が
既定値へ静かに戻る」形で壊れるため、HTML を正規表現で読んで項目一致を検証する
テストを `test_page_routes.py` に追加した (ブラウザ起動不要)。

---

## 保留中の検討課題

- [ ] FastAPIルートで `model_validate()` を手動呼びすると `ValidationError` が捕捉されず500になる問題のlint化
  - 現状: `settings_routes.py` は型付きパラメータ (`body: DynamicSettings`) 化済みで正しいが、`proofread_routes.py:28,37` の2箇所はまだ手動 `model_validate()` を呼んでおり違反している(この2箇所は軽微な実装修正としてその場で直せる)
  - 課題: `ruff`/`mypy` にはこのFastAPI固有パターンを検知するルールが無く、Fraetorには既存のカスタムlint基盤・PostToolUse/Stopの品質チェックhookも未整備(csp-voc-lambdaの`check_code_quality.sh`相当が無い)
  - 検討したい対応案: (A) `.semgrep/warn-manual-model-validate.yml` を1本書いてAST的に検出(semgrepという新規軽量依存が1つ増える) (B) `flake8`のカスタムプラグイン基盤をFraetorに新設し同パターンを検出(Aより新設コストが高いが、csp-voc-lambdaの`tools/`配下の既存プラグインと同型にできる)。**Bの方向で進める。** ただしプラグイン基盤の新設は実装コストが軽くないため、まずこの起票で留め、着手は別途判断する
  - 背景: いずれの案でも、まずcsp-voc-lambdaと同様にPostToolUse/Stopでruff+mypyを自動実行するhookをFraetorに整備するのが前提として先にある可能性がある(このissue固有の話ではなくFraetorのlint運用全体の話)

## 完了済み: 初期実装 (Phase 1-9)

- [x] Phase 1: プロジェクト基盤 (pyproject.toml, __main__.py, config.py)
- [x] Phase 2: FastAPI + ブラウザUI + SSE (app.py, sse.py, routes.py, index.html)
- [x] Phase 3: ホットキー + 状態管理 (state.py, hotkey.py, models.py)
- [x] Phase 4: 音声キャプチャ + Azure STT (audio.py, stt.py)
- [x] Phase 5: セッションマネージャ + SSE統合 (session_manager.py, 3分タイムアウト)
- [x] Phase 6: クリップボード + 自動ペースト (clipboard.py, session_manager統合)
- [x] Phase 7: Gemini 校正 (correction.py, correction_worker, 校正待機)
- [x] Phase 8: 履歴 (history.py, /api/history, 履歴タブ)
- [x] Phase 9: エラーハンドリング + 仕上げ (APIキー未設定, 権限エラー, フォールバック, 構造化ログ)
