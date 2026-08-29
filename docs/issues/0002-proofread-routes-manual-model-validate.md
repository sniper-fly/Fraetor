# 0002: proofread_routes.py の手動 model_validate() が 500 を返す

## 現状

`src/presentation/routes/proofread_routes.py:28,37` で `model_validate()` を手動呼びしている
(`body = ProofreadRequest.model_validate(await request.json())` / `FinalizeSessionRequest` 側も同型)。
FastAPI のハンドラ内でこの呼び方をすると `ValidationError` が FastAPI に捕捉されず、
422(自動バリデーションエラー)ではなく 500 になる。

`src/presentation/routes/settings_routes.py` は既に型付きパラメータ(`body: DynamicSettings`)で
受ける形へ修正済みで、同種の問題は解消している。

## 課題

クライアントが不正なボディを送った際にAPIが422ではなく500を返し、エラーの意味(クライアント起因か
サーバー起因か)がHTTPステータスから読み取れなくなる。この問題は一度発見済みで、機械的に検知する
手段として (A) semgrep 新規導入 と (B) flake8 カスタムプラグイン新設(csp-voc-lambda の `tools/` と同型)
を比較検討し、B案で進める方針までは決まっているが、実装(hookへの接続)は未着手。

## 検討したい対応案

1. `proofread_routes.py:28,37` を `settings_routes.py` と同様に型付きパラメータで受ける形へ修正する
2. B案(flake8カスタムプラグイン)を実装し、PostToolUse hook等から自動検知できるようにする
3. 対応1を先に適用し、対応2(機械的検知の仕組み)は別途優先度をつけて着手する

## 背景

2026-08-11 のセッションで、動的設定UIのハンドラ実装時に `model_validate()` を手動で呼ぶと
ValidationErrorが未捕捉のまま500になることが判明し、`settings_routes.py` では型付きパラメータへの
変更で回避した。その際 `proofread_routes.py` に同型の未修正箇所が2箇所残っていることも特定済み。
`todo.md` に検討課題として記録されていたが、`todo.md` は今回のプロジェクトの短期スコープの設計書であり
将来の変更要件を記載する場所ではないため、この issue として `docs/issues/` へ移した。
