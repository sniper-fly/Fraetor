PostToolUse hookによって型、リンタ、フォーマッタ、テストのチェックが行われるので明示的な実行は検証手順には含めない
検証手順には臨機応変に設計レベル、統合レベルの観点を含める。例えば以下の観点を含めること:

- 設計ドキュメントとの整合性

以下はテスト観点に含めない

- 自明なこと
- Pydanticなど外部ライブラリで保証されている機能(frozen検証など)

プライベート関数は乱立させない。関心が異なるモジュールは別クラス、別モジュールにする。

ユーザーに迎合しない。反証できる点がある場合はAskUserQuestionなどを利用し、ユーザーに確認を求める

dataclassではなく、pydanticのBaseModelを利用する。

不明な点があればAskUserQuestionを利用し、ユーザーに確認を求める

必ずテストを実装すること

依存関係追加はpyproject.tomlを直接編集せず、 uv add で最版安定版追加する

pythonコマンドを単体で使うのではなく、基本的にuv runなどを利用する

## E2Eテスト実行時の注意

`pytest-playwright` (同期API) と `pytest-asyncio` には既知の非互換性がある(Playwright の同期クライアントがプロセス内に専用イベントループを立てっぱなしにするため)。`tests/e2e/test_browser_ui.py` (Playwright使用) と他の非同期E2Eテストを同一 `pytest` セッションで実行すると、2つ目以降の非同期テストが `RuntimeError: Runner.run() cannot be called from a running event loop` で失敗する。README.md記載の2コマンド分割 (`--ignore=tests/e2e/test_browser_ui.py` と単独実行) を必ず守ること。1コマンドでの一括実行はできない。

E2Eテスト(`tests/e2e/`配下)は実クラウド通信・実プロセス起動を伴うため、勝手に実行しない。一区切り(タスク完了時など)ついたタイミングで、実行してよいかユーザーに確認を求めること。

AWSを使うコマンド(E2Eテスト含む)は`AWS_PROFILE`を必ず明示指定して実行する。
使うプロファイル名と、明示しないと落ちる理由は`CLAUDE.local.md`を参照。
`.env`に書いてあるから大丈夫、と判断してはならない。

## アーキテクチャ: 4層クリーンアーキテクチャ + DIコンテナ

Domain / Application / Infrastructure / Presentation の4層構成を採用する。
境界づけられたコンテキストは単一(`dictation`/`transcript_history`/
`proofreading`の3モジュールに内部分割、各モジュール内をレイヤー化)。

依存方向: Presentation → Application → Domain, Infrastructure → Domain
(逆方向のimport禁止。Presentationはcontainers.py経由の具象/ポートのみ使う)

- Domain: 純粋なPydanticモデルとポート(ABC)のみ。サードパーティSDK禁止。
- Application: ユースケース/オーケストレーション。ポート型にのみ依存。
- Infrastructure: ポートの実装。サードパーティSDK依存はここに閉じ込める。
- Presentation: HTTP変換のみ。ビジネスロジックはApplicationに委譲。

外部依存を新規追加する場合は、必ず対応モジュールの`domain/ports.py`に
ABCを定義し、`infrastructure/`配下に実装する(切り替え予定の有無を問わず、
一貫してポート抽象化する)。

DIコンテナは`dependency-injector`を使用し、`src/containers.py`の
`Container`に一元化する。手動DIをapp.py/__main__.pyに直接書くことを禁止。
FastAPIルートへの`@inject`+`Provide[]`wiringは使用しない(mypy strict
との相性問題のため)。`src/containers.py`のみ型安全性の緩和を許容する。

## dictationモジュール(外部ライブラリ)

音声認識機能(旧`src/dictation/`)は[fraetor-dictation](https://github.com/sniper-fly/fraetor-dictation)
として切り出し済み。Fraetorは`uv add`でgitタグ指定して依存し、
importパッケージ名は`dictation`(`src.dictation`ではない)。
`SegmentLifecycleHookPort`/`RecognizedTextTransformPort`/
`SessionFinalizationHookPort`等のポートはこのライブラリのdomain層に
定義されており、Fraetor側の実装(`intent_translation`/`transcript_history`)
がアダプタとして接続する。

dictation自体の改良(バグ修正・機能追加)はこのリポジトリではなく
fraetor-dictationリポジトリ側で行う。ローカルのクローン先は
`CLAUDE.local.md`を参照。

### Fraetorとdictationの責務境界(必ず守る)

音声入力まわりに機能を足す・変更するときは、**実装を始める前に**
[責務境界の正本 `docs/boundary.md`](https://github.com/sniper-fly/fraetor-dictation/blob/main/docs/boundary.md)
を読み、置き場所を判断フローで決めること。ローカルでは
`CLAUDE.local.md`のクローン先の`docs/boundary.md`を読む。
ドキュメントと食い違う変更が必要なら、実装せずユーザーに確認する。

要点(詳細・実例は正本を参照):

- **dictation(ライブラリ)に置く**: 録音セッション、無音区切り、STT/VAD/マイク、
  SSE配信、STTイベント型、拡張点の「口」(ポートのABC)
- **Fraetorに置く**: 設定の保存・UI、資格情報(SSM)、認識結果の永続化・後処理
  (校正・意図翻訳・Herdr送信)、HTTPルート、`containers.py`、
  拡張点の「中身」(アダプタ)
- 迷ったら**Fraetorに置く**。2つ目のホストが必要とした時点でライブラリへ移す
- Fraetorは`dictation`を**層ごとの公開口**(`dictation.domain.ports`、
  `dictation.application.*`、infrastructureのfactory)経由で使う。
  `from dictation import X`の一括importは使わない(全層を再exportするため、
  import-linterの「PresentationはInfrastructure具象をimportしない」検証が無効になる)。
  `MaiTranscribeClient`等の具象クラスは直接importせず、factory経由で使う。
  継承・上書き・monkeypatch・コードのコピーもしない
- Fraetor固有の関心事(履歴用フィールド等)を、ライブラリのドメインモデルに載せない
- 両方に変更が及ぶ場合は、ライブラリを先に変更・テスト・タグ付け・pushしてから、
  Fraetor側で`uv add`してタグを進める

