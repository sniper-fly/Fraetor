## phase1: Herdrクライアント (Socket API/CLI呼び出し)
目的: 既存の3境界づけられたコンテキストに属さない外部システムクライアントを`src/shared/herdr/`に新設し、単体で動作確認できる状態にする。

- [x] `src/shared/herdr/ports.py`  # HerdrSessionInfo/HerdrClientPort定義
- [x] `src/shared/herdr/socket_client.py`  # HerdrSocketClient実装 (Socket API + CLI subprocess)
- [x] `tests/shared/herdr/test_socket_client.py`  # 単体テスト

## phase2: dictation拡張・DI配線・新規エンドポイント
目的: Herdrクライアントを使い、録音セッション単位でtarget_pane_idを記録するトグルエンドポイントと、セッション一覧/送信用エンドポイントを配線する。

- [x] `src/dictation/domain/models.py`  # RecordingSession.target_pane_id追加
- [x] `src/dictation/application/recording_session_service.py`  # start_session/stop_sessionへのオプション引数追加、statusイベント拡張
- [x] `tests/dictation/application/test_recording_session_service.py`  # 追加引数・イベント内容のテスト
- [x] `src/shared/config/dynamic_settings.py`  # herdr_slot_count追加
- [x] `src/presentation/schemas/request_models.py`  # SendToHerdrRequest追加
- [x] `src/presentation/routes/herdr_routes.py`  # 3エンドポイント実装
- [x] `tests/presentation/test_herdr_routes.py`  # 3エンドポイントのテスト
- [x] `src/containers.py`  # herdr_client provider追加
- [x] `src/presentation/app.py`  # app.state.herdr_client配線、herdr_routes.router登録
- [x] `toggle-recording-and-send-to-herdr.sh`  # 新規ショートカットスクリプト

## phase3: フロントエンド (複数ブロック表示・送信) + ドキュメント更新
目的: メイン画面を単一ブロック表示から直近4件の複数ブロック表示に変更し、各ブロックの送信先選択・手動送信・自動送信・トーストを実装する。仕上げにdesign.mdへ反映する。

- [ ] `src/templates/index.html`  # sessionQueue拡張、tryAdvanceQueue修正 (重複処理防止含む)、status/SSEハンドラ拡張、複数ブロック表示・ドロップダウン・送信ボタン、トースト一般化、設定フィールド追加
- [ ] `design.md`  # Herdr送信経路 (新たな出力先) の追記
