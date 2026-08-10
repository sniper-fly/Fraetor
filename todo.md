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

- [ ] `src/shared/config/settings.py`  # 動的化対象フィールドの削除 (除外項目は残す)
- [ ] `tests/shared/config/test_settings.py`  # 削除に追随
- [ ] `src/dictation/infrastructure/vad/factory.py`  # create_vad を新設し vad_threshold を遅延読み込み
- [ ] `tests/dictation/infrastructure/vad/test_factory.py`  # 上記に対応する単体テスト
- [ ] `src/dictation/infrastructure/stt/factory.py`  # settings_repository を受け取る signature へ変更
- [ ] `tests/dictation/infrastructure/stt/test_factory.py`  # 上記に対応する単体テスト
- [ ] `src/dictation/application/recording_session_service.py`  # start_session 実行時に get()
- [ ] `tests/dictation/application/test_recording_session_service.py`  # 「次回反映」の検証を追加
- [ ] `src/proofreading/application/proofread_text_use_case.py`  # execute 実行時に get()
- [ ] `tests/proofreading/application/test_proofread_text_use_case.py`  # 「次回反映」の検証を追加
- [ ] `src/presentation/routes/shutdown_routes.py`  # リクエスト時に shutdown_delay_sec を読む
- [ ] `tests/presentation/routes/test_shutdown_routes.py`  # 上記に追随
- [ ] `src/presentation/routes/recording_routes.py`  # SSE 接続時に sse_keepalive_sec を読む
- [ ] `tests/presentation/routes/test_recording_routes.py`  # 上記に追随
- [ ] `src/presentation/app.py`  # lifespan で app.state.settings_repository を設定
- [ ] `src/containers.py`  # settings_repository の Singleton 追加と各 provider の配線変更
- [ ] `tests/test_containers.py`  # 配線変更に追随

### phase3: 無音区切りによる逐次 flush
目的: VAD の発話開始位置公開から STT の部分送信、無音監視タイマー、コーディネータ統合までを一続きで実装する。`SegmentAccumulator` / SSE / フロントエンドは変更しない (プラン §5 の通り、既存経路がそのまま機能することを既存テストで担保する)。

- [ ] `src/dictation/domain/ports.py`  # last_speech_start_sample プロパティと SttEnginePort.flush を追加
- [ ] `src/dictation/infrastructure/vad/silero_vad_detector.py`  # VADIterator の start を保持
- [ ] `tests/dictation/infrastructure/vad/test_silero_vad_detector.py`  # 上記に対応する単体テスト
- [ ] `src/dictation/infrastructure/stt/mai_transcribe_client.py`  # 累積バッファ + 送信済みオフセット方式へ書き換え、flush 実装、stop の最終区間処理
- [ ] `tests/dictation/infrastructure/stt/test_mai_transcribe_client.py`  # オフセット追随・trim・no-op ガード・例外非伝播の検証
- [ ] `src/dictation/application/segment_silence_monitor.py`  # 残り時間だけ寝る監視ループ (重複呼び出しは許容)
- [ ] `tests/dictation/application/test_segment_silence_monitor.py`  # 上記に対応する単体テスト
- [ ] `src/dictation/application/audio_pipeline_coordinator.py`  # SegmentSilenceMonitor 組み込みと asyncio.Lock による flush 直列化
- [ ] `tests/dictation/application/test_audio_pipeline_coordinator.py`  # 起動/停止・flush 引数・直列化の検証
- [ ] `src/containers.py`  # audio_pipeline_coordinator への segment_silence_sec 経路を配線
- [ ] `tests/test_containers.py`  # 配線変更に追随

### phase4: 設定 API・設定画面・ドキュメント整合
目的: 動的設定をブラウザから編集できるようにし、設計ドキュメントを実装に追随させる。

- [ ] `src/presentation/routes/settings_routes.py`  # GET / PUT /api/settings (DynamicSettings を直接 I/O モデルに使う)
- [ ] `tests/presentation/routes/test_settings_routes.py`  # 取得・更新の反映・不正値で 422 の検証
- [ ] `src/presentation/app.py`  # settings_routes の router 登録
- [ ] `src/templates/index.html`  # 「設定」タブ追加、switchTab の3値対応、loadSettings / saveSettings
- [ ] `design.md`  # 定数章・VAD 章・データフロー章の更新と「動的設定」章の新設
- [ ] 実装完了後、E2E テスト (特に `tests/e2e/test_mic_and_vad.py` / `test_mai_transcribe.py`) の実行可否をユーザーに確認する
- [ ] 3秒以上の無音を挟んだ発話で逐次追記されること・リードタイム短縮を実機で手動確認する

---

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
