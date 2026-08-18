from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_DEFAULT_PROOFREAD_PROMPT = (
    "音声認識で得られたテキストを校正してください。以下のルールに従ってください:\n"
    "- 誤字脱字、変換ミスを修正する\n"
    "- 不要な句読点や余分な記号を除去する\n"
    "- フィラーワード(えー、あの、えっと等)を除去する\n"
    "- 元のテキストの意味や表現をできる限り変えない\n"
    "- 校正結果のテキストのみを返す(説明や補足は一切付けない)"
)

_DEFAULT_INTENT_TRANSLATION_PROMPT = (
    "あなたの役割は、ユーザーの音声認識結果とその時点の画面スクリーンショットを基に、\n"
    "別のコーディングエージェントへ送る依頼文プロンプトを作成することです。\n"
    "\n"
    "対象特定の手順(この順序で必ず確認してください):\n"
    "1. まず画面内のコードエディタのメインペイン(ソースコードが表示されている領域)を探"
    "してください。\n"
    "2. その中で、背景色が周囲と異なる(反転・ハイライトされている)行や単語を探してくだ"
    "さい。これが\n"
    "   ユーザーが選択操作中のテキストです。ステータスバーに \"Ln xx, Col xx (n selecte"
    "d)\" のような\n"
    "   表示があれば、それも選択中である根拠として使ってください。\n"
    "3. 選択されているテキストが含まれるファイル名・行番号・関数名やコード内容を具体的"
    "に読み取ってください。\n"
    "   画面上部にファイルパスのパンくずリスト(breadcrumb)が表示されている場合は、それ"
    "を使って\n"
    "   対象ファイルの正確なパスを特定してください。\n"
    "4. ユーザーの発話中の指示語(これ/ここ/それ/さっきの、等)は、上記2〜3で特定した選択"
    "中のコードを\n"
    "   指すものとして解釈してください。\n"
    "5. エラーダイアログ、通知ポップアップ、サイドバーのアイコンなど、選択中のコードと"
    "無関係に画面上に\n"
    "   表示されているだけの要素は、指示語の対象として採用しないでください。\n"
    "6. 画面のハイライト・選択状態は、あくまで「どの行・どの範囲が対象か」を特定するた"
    "めの内部的な\n"
    "   手がかりとして使ってください。特定できた対象(行番号・関数名・コード内容)は、こ"
    "れまでと同じ\n"
    "   精度で具体的に記述してください。禁止するのは「選択されている」「ハイライトされ"
    "ている」\n"
    "   「カーソルがある」といったUI操作状態を表す言葉そのものを依頼文の文章内に書くこ"
    "とだけです。\n"
    "   この言葉を避けるために、対象の行番号や範囲を広げたり曖昧にしたりしないでくださ"
    "い。\n"
    "   特定できているなら、その1行(または実際に選択されている範囲)だけを正確に指してく"
    "ださい。\n"
    "7. 生成する依頼文の範囲は、ユーザーの発話が実際に求めている内容に厳密に限定してく"
    "ださい。発話に\n"
    "   含まれていない追加の質問項目や作業内容(処理の流れの説明、特定の変数の役割への言"
    "及、等)を、\n"
    "   親切心で勝手に付け加えないでください。ユーザーの発話が単純な質問であれば、依頼"
    "文も同程度\n"
    "   シンプルにまとめてください。\n"
    "\n"
    "重要な制約:\n"
    "- あなた自身がユーザーの質問に回答したり、画面内容を調査・説明したりしてはいけませ"
    "ん。\n"
    "  あなたの出力は「次にコーディングエージェントへ渡す依頼文」そのものであり、回答で"
    "はありません。\n"
    "- 発話内容が画面文脈の補完を必要としない(自己完結している)、または「えーっと」「あ"
    "の」のような\n"
    "  意味のあるタスクを含まないフィラー・言い淀みのみである場合は、新しい依頼文を作ら"
    "ず、\n"
    "  音声認識結果の文章をそのまま(一字一句変更せず)出力してください。ユーザーが何も指"
    "示していないのに\n"
    "  画面内容から推測して新たな依頼を作り出してはいけません。\n"
    "- 出力は変換後の依頼文プロンプトのみとしてください。前置き・説明・見出し・コードブ"
    "ロックは一切\n"
    "  付けず、1文の自然な疑問文または依頼文としてまとめてください。"
)


class Settings(BaseModel):
    """起動時に確定する静的な定数群。シークレットは含まない
    (secrets_loader.Secrets 参照)。

    実行中に変更できる値は `DynamicSettings` に置く。ここに残すのは
    「変更にプロセス再起動が必要」なもの (TCP bind、Singleton に紐づく
    リソース、データ配置) に限る。
    """

    model_config = ConfigDict(frozen=True)

    # --- STT 共通 (audio_capture Singleton のマイクストリームに紐づく) ---
    stt_sample_rate: int

    # --- サーバー (TCP bind は起動時に確定する) ---
    server_host: str
    server_port: int

    # --- 校正 (Proofreading クライアント Singleton の生成に紐づく) ---
    vertex_location: str
    gemini_model: str
    proofread_prompt: str

    # --- 意図翻訳 (IntentTranslator クライアント Singleton の生成に紐づく) ---
    azure_openai_api_version: str
    intent_translation_model_name: str
    intent_translation_prompt: str

    # --- 履歴 (実行中の切り替えはデータ配置の整合性を崩す) ---
    history_dir: Path


def load_settings() -> Settings:
    """環境変数オーバーライドを適用して Settings を構築する。

    環境変数は E2E テストでポート・履歴ファイルを隔離された値に
    変更するためのもの。タイムアウト系は `DynamicSettings`
    (設定ファイル経由) へ移ったため、ここでは扱わない。
    """
    history_dir = Path(
        os.environ.get("FRAETOR_HISTORY_DIR", "~/.voice-input")
    ).expanduser()
    return Settings(
        stt_sample_rate=16000,
        server_host="127.0.0.1",
        server_port=int(os.environ.get("FRAETOR_SERVER_PORT", "8765")),
        vertex_location="global",
        gemini_model="gemini-3.1-flash-lite-preview",
        proofread_prompt=_DEFAULT_PROOFREAD_PROMPT,
        azure_openai_api_version="2024-08-01-preview",
        intent_translation_model_name="gpt-5.6-luna",
        intent_translation_prompt=_DEFAULT_INTENT_TRANSLATION_PROMPT,
        history_dir=history_dir,
    )
