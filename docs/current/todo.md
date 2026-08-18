## phase1: dictationモジュールの拡張点追加
目的: `intent_translation`モジュールがまだ存在しない状態で、`dictation`側に汎用フックポートと`SttEnginePort.flush()`の戻り値変更を先に入れる。フックは`None`許容のオプショナル依存とし、既存動作(フック未注入時)を変えない。

- [x] `src/dictation/domain/ports.py`  # `SegmentLifecycleHookPort`(on_speech_start/on_flush(produced_text)/reset)、`RecognizedTextTransformPort`(transform)を追加。`SttEnginePort.flush()`の戻り値を`None`から`str`に変更(docstring含む)
- [x] `src/dictation/infrastructure/stt/mai_transcribe_client.py`  # `flush()`が計算済みの`text`を返すよう変更(空送信時は`""`を返す)
- [x] `src/dictation/application/audio_pipeline_coordinator.py`  # `__init__`に`segment_lifecycle_hook: SegmentLifecycleHookPort | None = None`を追加。`start()`で`reset()`呼び出し、`_on_audio_chunk`の発話開始検知箇所で`on_speech_start()`呼び出し、`_flush_segment`で`flush()`の戻り値を受けて`on_flush(produced_text=bool(text))`呼び出し。`stop()`は変更しない(理由はspec.md「設計上の修正」節参照)
- [x] `src/dictation/application/segment_accumulator.py`  # `__init__`に`text_transform: RecognizedTextTransformPort | None = None`を追加。`handle_event`の`"recognized"`分岐で`Segment`生成前に`transform(session.id, text)`を通す
- [x] `tests/dictation/application/test_audio_pipeline_coordinator.py`  # `segment_lifecycle_hook`のMagicMockを注入し、`reset`/`on_speech_start`(初回検知のみ)/`on_flush(produced_text=True/False)`が正しいタイミングで呼ばれること、`None`時に既存テストが全通ることを検証
- [x] `tests/dictation/application/test_segment_accumulator.py`  # `text_transform`のAsyncMockを注入し、`recognized`イベントで`transform`が呼ばれ戻り値が`Segment.text`になること、`interim`イベントでは呼ばれないこと、`None`時に既存テストが全通ることを検証
- [x] `tests/dictation/application/test_recording_session_service.py`  # 383行目付近のインライン`flush`フェイクの戻り値を`-> str`(空文字列を返す)に変更し、既存テストが崩れないことを確認
- [x] `tests/dictation/infrastructure/stt/test_mai_transcribe_client.py`  # `flush()`が認識結果テキストを返すこと/空文字列を返すことのテストを追加

## phase2: intent_translationモジュールの新設
目的: `docs/current/spec.md`の確定システムプロンプト・API仕様(`max_completion_tokens`必須等)に基づき、`proofreading`モジュールと同型の4層構成(domain/application/infrastructure)で`intent_translation`モジュール本体を実装する。この時点では`dictation`/`containers.py`とは未接続(単体で完結)。

- [x] `src/intent_translation/domain/ports.py`  # `ScreenshotCapturePort`(capture)、`IntentTranslatorPort`(translate)
- [x] `src/intent_translation/application/segment_screenshot_pairer.py`  # `SegmentScreenshotPairer`(`_pending`/`_ready`の状態機械、`on_speech_start`/`on_flush(produced_text)`/`pop_ready`/`reset`)
- [x] `src/intent_translation/application/intent_translation_use_case.py`  # `IntentTranslationUseCase`(`ProofreadTextUseCase`と同型のフォールバック構造)
- [x] `src/intent_translation/application/dictation_hook_adapter.py`  # `IntentTranslationDictationAdapter`(`SegmentLifecycleHookPort`/`RecognizedTextTransformPort`を実装し、`SegmentScreenshotPairer`と`IntentTranslationUseCase`を橋渡し)
- [x] `src/intent_translation/infrastructure/screenshot/mss_screenshot_capturer.py`  # `MssScreenshotCapturer`(プラットフォーム分岐なしの単一実装、macOS環境でのみ動作検証、Linux対応はコード上のみ)
- [x] `src/intent_translation/infrastructure/azure_openai_intent_translator.py`  # `AzureOpenAIIntentTranslator`(`AsyncAzureOpenAI`、`max_completion_tokens`使用、画像は`image_url`のdata URL形式)
- [x] `tests/intent_translation/application/test_segment_screenshot_pairer.py`  # ON/OFF切替、`on_flush(produced_text=False)`で`_ready`に積まれないこと、FIFO順序、`reset`
- [x] `tests/intent_translation/application/test_intent_translation_use_case.py`  # `translator=None`/`enabled=False`/`screenshot=None`/成功/例外・タイムアウト時のフォールバック
- [x] `tests/intent_translation/application/test_dictation_hook_adapter.py`  # 委譲呼び出しの検証(pop_readyがNoneの場合は原文を返す等)
- [x] `tests/intent_translation/infrastructure/screenshot/test_mss_screenshot_capturer.py`  # `@patch(".mss")`でモック、範囲外index、例外時`None`
- [x] `tests/intent_translation/infrastructure/test_azure_openai_intent_translator.py`  # `max_completion_tokens`使用の検証、空テキスト即返し、`content`空時のフォールバック

前倒し実施(phase2のApplication層がDynamicSettingsのフィールドに型として依存するため、
phase3の一部を先に済ませた): `src/shared/config/dynamic_settings.py`への3フィールド追加、
`uv add openai mss`、`pyproject.toml`の`mss.*`向けmypy override追加。
`tests/presentation/routes/test_page_routes.py`の`test_settings_fields_cover_all_dynamic_settings`
は、`intent_translation_enabled`(専用トグルボタン予定)と`screenshot_monitor_index`/
`intent_translation_timeout_sec`(phase3のUI実装まで未接続)を除外リストで除外するよう更新済み。

## phase3: 設定・DI配線・UI接続
目的: phase1のフックとphase2のモジュールを`containers.py`で接続し、設定項目とフロントエンドトグルを追加して機能を有効化する。ドキュメント(`docs/image_recognition_prompt.md`)への反映もこのフェーズで行う。

- [x] `src/shared/config/dynamic_settings.py`  # `intent_translation_enabled: bool = False`、`screenshot_monitor_index: int = Field(default=1, ge=0)`、`intent_translation_timeout_sec: int = Field(default=20, gt=0)`を追加 (phase2で前倒し実施済み)
- [ ] `src/shared/config/settings.py`  # `azure_openai_api_version`、`intent_translation_model_name`、`intent_translation_prompt`(spec.md記載の確定システムプロンプトを定数化)を追加
- [ ] `src/containers.py`  # `_create_intent_translator`ファクトリ、`screenshot_capture`/`segment_screenshot_pairer`/`intent_translator`/`intent_translation_use_case`/`intent_translation_dictation_adapter`のProvider追加。既存`audio_pipeline_coordinator`/`segment_accumulator`のProviderに`segment_lifecycle_hook`/`text_transform`を接続
- [ ] `src/templates/index.html`  # 意図翻訳ON/OFFトグル(サーバー側`DynamicSettings.intent_translation_enabled`が真実源、`PUT /api/settings`を再利用)、`SETTINGS_FIELDS`に`screenshot_monitor_index`/`intent_translation_timeout_sec`を追加。追加後は`tests/presentation/routes/test_page_routes.py`の`_PENDING_PHASE3_FIELDS`からこの2項目を外す
- [x] `pyproject.toml`  # `uv add openai` / `uv add mss`。`[[tool.mypy.overrides]]`に`module = "mss.*"`の`ignore_missing_imports = true`を追加 (phase2で前倒し実施済み)
- [ ] `tests/test_containers.py`  # `test_intent_translator_is_none_without_mai_credentials`等、既存`test_proofreader_is_none_without_vertex_credentials`と対になるテストを追加
- [ ] `tests/presentation/routes/test_settings_routes.py`  # 新規3フィールドの更新確認を1〜2件追記
- [ ] 実装完了後、`docs/image_recognition_prompt.md`§5.6の未指定事項のうち本実装で解決した項目(撮影間隔・撮影タイミング・保存方針・切替方法・タイムアウト・校正との関係・マルチモニタ対応方針)を反映するかどうかをユーザーに確認し、合意が取れれば反映する
