# Fraetor 実装 TODO

- [x] Phase 1: プロジェクト基盤 (pyproject.toml, __main__.py, config.py)
- [x] Phase 2: FastAPI + ブラウザUI + SSE (app.py, sse.py, routes.py, index.html)
- [x] Phase 3: ホットキー + 状態管理 (state.py, hotkey.py, models.py)
- [x] Phase 4: 音声キャプチャ + Azure STT (audio.py, stt.py)
- [x] Phase 5: セッションマネージャ + SSE統合 (session_manager.py, 3分タイムアウト)
- [x] Phase 6: クリップボード + 自動ペースト (clipboard.py, session_manager統合)
- [x] Phase 7: Gemini 校正 (correction.py, correction_worker, 校正待機)
- [x] Phase 8: 履歴 (history.py, /api/history, 履歴タブ)
- [x] Phase 9: エラーハンドリング + 仕上げ (APIキー未設定, 権限エラー, フォールバック, 構造化ログ)
