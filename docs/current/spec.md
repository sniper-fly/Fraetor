# 意図翻訳レイヤー(機能4)実装プラン

## Context

`docs/image_recognition_prompt.md` §5「機能4: 意図翻訳レイヤー」を実装する。録音中、無音区間で区切られた発話セグメントごとに画面スクリーンショットを1枚撮影し、発話終了で得られた認識結果テキストとペアにして、Vision対応LLM(Azure Foundry上の`gpt-5.6-luna`)に渡し、「これ/ここ/それ」等の指示語を画面内容で具体化した、別のコーディングエージェント向け依頼文に変換する。目的はPRレビュー中などに「AIエージェントが見ている情報と人間が見ている情報を揃える」ことで、意図伝達の速度を上げること。

本実装に先立ち、以下を技術検証済み:
- `gpt-5.6-luna`はAzure Foundry上のリソース(`<your-resource>.cognitiveservices.azure.com`)にデプロイ済みで、既存のMAI用シークレット(`mai_api_key`/`mai_endpoint`、SSM経由)がそのまま使える(新規SSMパラメータ不要)。Azure OpenAI互換の`/openai/deployments/{deployment}/chat/completions`エンドポイントで画像入力(`image_url`のdata URL形式)を受け付ける。
- `max_tokens`は非対応で`max_completion_tokens`必須。reasoningトークンを消費するため、2000〜3000程度の余裕が必要(300では出力が空になった)。
- `mss`ライブラリでmacOSの複数ディスプレイのスクリーンショット撮影が可能(既存の画面収録権限で動作確認済み)。
- 実際のCursor画面+口語的な指示文("これどういう意味ですか？")を使い、以下の確定システムプロンプトで「選択中のコードを正しく特定し、UI状態を漏らさず、指示以上の補完をせず、フィラーのみの発話は原文を返す」という挙動を実機検証で確認済み(§2.11に転記)。

ユーザーとの確認により以下3点を確定済み:
1. **実行タイミング**: 発話区切り(無音区間)ごとに即時実行(送信操作時にまとめて処理する元ドキュメント§5.3の方式は採らない)。
2. **スクリーンショット保存方針**: 変換に使ったら即時破棄。ディスクにも履歴にも一切保存しない。
3. **プラットフォーム対応方針(要件)**: スクリーンショット撮影機能はmacOSに最適化した実装にしない。既存の`pyperclip`(クリップボードコピー)と同様に、`sys.platform`による分岐を書かずに単一実装でマルチプラットフォーム対応する設計を要件とする。ただし本実装フェーズでの動作検証はmacOS環境のみで行い、Linux環境での実機検証は対象外とする(コード上はLinuxでも動く設計にするが、実際にLinux上で動くことの確認はしない)。

## アーキテクチャ

既存の`proofreading`モジュールと同じ4層構成で新規モジュール`src/intent_translation/`を追加する。校正機能はPresentation層(HTTPルート)からしか呼ばれず`dictation`の内部を知らないが、今回は「発話開始検知」「無音確定(flush)」という`dictation`内部のタイミングそのものが必要になる。素朴に`intent_translation`の具象クラスを`dictation`に直接importさせると、境界づけられたコンテキスト間の禁止された依存(`dictation → intent_translation`)が生まれるため、`dictation/domain/ports.py`に汎用フックポートを2つ追加し、`intent_translation`側のアダプタがそれを実装する形にする。依存の矢印は常に「`intent_translation` → `dictation.domain`(抽象)」のみで、`containers.py`(合成ルート)だけが両方を知る。

```
src/dictation/domain/ports.py          … SegmentLifecycleHookPort, RecognizedTextTransformPort を追加
src/dictation/domain/ports.py          … SttEnginePort.flush() の戻り値を str に変更 (下記「設計上の修正」参照)
src/dictation/infrastructure/stt/mai_transcribe_client.py  … flush() が text を返すよう変更
src/dictation/application/audio_pipeline_coordinator.py    … フック呼び出し追加
src/dictation/application/segment_accumulator.py           … フック呼び出し追加

src/intent_translation/
  domain/ports.py                      … ScreenshotCapturePort, IntentTranslatorPort
  application/
    segment_screenshot_pairer.py       … SegmentScreenshotPairer (状態機械、I/Oなし)
    intent_translation_use_case.py     … IntentTranslationUseCase (ProofreadTextUseCaseと同構造)
    dictation_hook_adapter.py          … IntentTranslationDictationAdapter (dictationの2ポートを実装)
  infrastructure/
    screenshot/mss_screenshot_capturer.py  … MssScreenshotCapturer
    azure_openai_intent_translator.py      … AzureOpenAIIntentTranslator

src/containers.py                      … DI配線
src/shared/config/dynamic_settings.py  … intent_translation_enabled, screenshot_monitor_index, intent_translation_timeout_sec
src/shared/config/settings.py          … azure_openai_api_version, intent_translation_model_name, intent_translation_prompt
src/templates/index.html               … トグルUI + JS
pyproject.toml                         … uv add openai / uv add mss
```

## 設計上の修正: セグメントとスクリーンショットの対応付け

レビューで発見した不整合: `MaiTranscribeClient.flush()`は音声を送っても**認識結果が空文字列なら`recognized`イベントを一切発行しない**(`_transcribe()`内の`if text: self._queue.put_nowait(...)`)。もし「flushが呼ばれた」ことだけを根拠にスクリーンショットをFIFOキューに積むと、無音・雑音のみでVADが誤検知したセグメントで`recognized`イベントが発行されず、そのスクリーンショットが誰にも消費されずキューに残り、以降の全セグメントのスクリーンショット対応が1つずつずれる(以後のセッション全体で誤った画像とテキストがペアになる)。

**修正**: `SttEnginePort.flush()`の戻り値を`None`から`str`(認識結果テキスト、空文字列可)に変更する。`MaiTranscribeClient.flush()`は既に内部で`text`を計算しているので`return text`を追加するだけで済む(`src/`内の`SttEnginePort`実装は`MaiTranscribeClient`のみ、確認済み。`tests/dictation/application/test_recording_session_service.py:383`のインラインfakeも同様に戻り値を追加する必要がある)。

`AudioPipelineCoordinator._flush_segment`は`text = await stt_client.flush(...)`で戻り値を受け取り、`hook.on_flush(produced_text=bool(text))`として渡す。`SegmentScreenshotPairer`は`produced_text=True`のときだけ`_pending`を`_ready`キューに積み、`False`なら(recognizedイベントが来ないので)`_pending`を捨てる。これにより「`_ready`への追加」と「`recognized`イベントの発行」が常に1:1で対応する。

もう一点の修正: `AudioPipelineCoordinator.stop()`は`stt_client.stop()`をここでは呼ばない(呼び出し元が`TranscriptionQueue`にジョブとして委譲する非同期処理、`stop()`のdocstring参照)。したがって`stop()`内でフックを呼んでも実際の最終送信タイミングと一致しない。**`stop()`にはフックを追加しない**。結果として、無音区切りを一度も経ずに録音を止めた場合の末尾の発話(`stt_client.stop()`が最終セグメントとして送る分)は意図翻訳の対象にならず、生の認識結果のままになる。これは既存の「LLM呼び出し失敗時は原文フォールバック」という設計哲学と一致するスコープ限定であり、対応不要とする。

## 各ファイルの変更内容

### `src/dictation/domain/ports.py`

```python
class SegmentLifecycleHookPort(ABC):
    """発話区切りの生成タイミングに対する外部フック(意図翻訳レイヤー用の拡張点)。"""

    @abstractmethod
    def on_speech_start(self) -> None:
        """発話開始検知の瞬間(未flush区間で最初の1回のみ)に呼ばれる。"""

    @abstractmethod
    def on_flush(self, *, produced_text: bool) -> None:
        """flush完了直後に呼ばれる。produced_textはrecognizedイベントが
        発行される見込みか(認識結果が空でなかったか)を示す。"""

    @abstractmethod
    def reset(self) -> None:
        """セッション開始時に呼ばれる。前セッションの状態を残さない。"""


class RecognizedTextTransformPort(ABC):
    """recognizedイベントのテキストに対する変換フック。"""

    @abstractmethod
    async def transform(self, session_id: str, text: str) -> str:
        """テキストを必要に応じて変換して返す。変換不要/失敗時は元のテキストを返す。"""
```

`SttEnginePort.flush()`の型を`async def flush(self, *, trim_before_sample: int | None) -> str`に変更し、docstringに「戻り値は認識結果テキスト。空文字列ならrecognizedイベントは発行されない」を追記する。

### `src/dictation/infrastructure/stt/mai_transcribe_client.py`

`flush()`の`if not wav_bytes: return`を`return ""`に変更し、末尾に`return text`を追加(`text`は既存の`await self._transcribe(...)`の戻り値)。`stop()`は変更不要(フックの対象外)。

### `src/dictation/application/audio_pipeline_coordinator.py`

- `__init__`に`segment_lifecycle_hook: SegmentLifecycleHookPort | None = None`を追加。
- `start()`: `self._pending_speech_start_sample = None`の直後に`if self._segment_lifecycle_hook: self._segment_lifecycle_hook.reset()`を追加。
- `_on_audio_chunk`: `self._pending_speech_start_sample = start`の直後(新規発話開始検知時のみ)に`if self._segment_lifecycle_hook: self._segment_lifecycle_hook.on_speech_start()`を追加。
- `_flush_segment`: `text = await stt_client.flush(trim_before_sample=trim_before_sample)`に変更し、その直後に`if self._segment_lifecycle_hook: self._segment_lifecycle_hook.on_flush(produced_text=bool(text))`を追加。
- `stop()`: 変更なし(上記の理由でフックを追加しない)。

### `src/dictation/application/segment_accumulator.py`

- `__init__`に`text_transform: RecognizedTextTransformPort | None = None`を追加。
- `handle_event`の`"recognized"`分岐で、`Segment`を作る前に`if self._text_transform is not None: text = await self._text_transform.transform(session.id, text)`を挿入する。

### `src/intent_translation/domain/ports.py`(新規)

```python
class ScreenshotCapturePort(ABC):
    @abstractmethod
    def capture(self, monitor_index: int) -> bytes | None:
        """PNG形式のスクリーンショットを撮る。失敗時はNoneを返す(例外は伝播させない)。"""

class IntentTranslatorPort(ABC):
    @abstractmethod
    async def translate(self, text: str, screenshot_png: bytes) -> str:
        """認識結果テキストと画面スクリーンショットから依頼文を生成する。"""
```

### `src/intent_translation/application/segment_screenshot_pairer.py`(新規)

I/Oを持たない状態機械。`_pending: bytes | None`(発話開始ごとに上書き)と`_ready: deque[bytes | None]`(flush確定順のFIFO)を持つ。

```python
def on_speech_start(self) -> None:
    settings = self._settings_repository.get()
    if not settings.intent_translation_enabled:
        self._pending = None
        return
    self._pending = self._capture.capture(settings.screenshot_monitor_index)

def on_flush(self, *, produced_text: bool) -> None:
    if produced_text:
        self._ready.append(self._pending)
    self._pending = None

def pop_ready(self) -> bytes | None:
    return self._ready.popleft() if self._ready else None

def reset(self) -> None:
    self._pending = None
    self._ready.clear()
```

ON/OFFは呼ばれるたびに`settings_repository.get()`で読み直す(校正のタイムアウト読み直しと同じ「都度読む」方針)。

### `src/intent_translation/application/intent_translation_use_case.py`(新規)

`ProofreadTextUseCase`(`src/proofreading/application/proofread_text_use_case.py`)と同じフォールバック構造。

```python
async def execute(self, text: str, screenshot_png: bytes | None) -> tuple[str, bool]:
    settings = self._settings_repository.get()
    if self._translator is None or not settings.intent_translation_enabled or screenshot_png is None:
        return text, False
    try:
        result = await asyncio.wait_for(
            self._translator.translate(text, screenshot_png),
            timeout=settings.intent_translation_timeout_sec,
        )
    except Exception:
        logger.exception("Intent translation failed")
        return text, False
    return result, True
```

### `src/intent_translation/application/dictation_hook_adapter.py`(新規)

`dictation`の2ポートを実装し、`SegmentScreenshotPairer`と`IntentTranslationUseCase`を橋渡しする唯一の接続点。

```python
class IntentTranslationDictationAdapter(SegmentLifecycleHookPort, RecognizedTextTransformPort):
    def on_speech_start(self) -> None:
        self._pairer.on_speech_start()

    def on_flush(self, *, produced_text: bool) -> None:
        self._pairer.on_flush(produced_text=produced_text)

    def reset(self) -> None:
        self._pairer.reset()

    async def transform(self, session_id: str, text: str) -> str:
        screenshot = self._pairer.pop_ready()
        if screenshot is None:
            return text
        translated, _ = await self._use_case.execute(text, screenshot)
        return translated
```

### `src/intent_translation/infrastructure/screenshot/mss_screenshot_capturer.py`(新規)

```python
class MssScreenshotCapturer(ScreenshotCapturePort):
    def capture(self, monitor_index: int) -> bytes | None:
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                if not 0 <= monitor_index < len(monitors):
                    logger.warning("screenshot_monitor_index=%d が範囲外です", monitor_index)
                    return None
                shot = sct.grab(monitors[monitor_index])
                return mss.tools.to_png(shot.rgb, shot.size)
        except Exception:
            logger.exception("Screenshot capture failed")
            return None
```

プラットフォーム分岐(`AudioCapturePort`の`factory.py`のようなdarwin/other分岐)は不要と判断する。`mss`がプラットフォーム差をライブラリ内部で吸収するため。

### `src/intent_translation/infrastructure/azure_openai_intent_translator.py`(新規)

```python
_MAX_COMPLETION_TOKENS = 2500  # 実測: 300で失敗、2000で成功。余裕を持たせる

class AzureOpenAIIntentTranslator(IntentTranslatorPort):
    def __init__(self, *, endpoint: str, api_key: str, deployment: str, api_version: str, prompt: str) -> None:
        self._client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        self._deployment = deployment
        self._prompt = prompt

    async def translate(self, text: str, screenshot_png: bytes) -> str:
        if not text.strip():
            return text
        image_data_url = f"data:image/png;base64,{base64.b64encode(screenshot_png).decode('ascii')}"
        response = await self._client.chat.completions.create(
            model=self._deployment,
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
            messages=[
                {"role": "system", "content": self._prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]},
            ],
        )
        content = response.choices[0].message.content
        return content.strip() if content else text
```

`max_tokens`ではなく`max_completion_tokens`を使う(実機検証済み、`max_tokens`だと400エラー`unsupported_parameter`)。API例外はキャッチせず伝播させる(`VertexGeminiProofreader`と同方針、フォールバックはuse case層の責務)。

### `src/shared/config/dynamic_settings.py`(追加フィールド)

```python
intent_translation_enabled: bool = False
screenshot_monitor_index: int = Field(default=1, ge=0)
intent_translation_timeout_sec: int = Field(default=20, gt=0)
```

`intent_translation_enabled`の既定値は`False`(画面収録を伴うためopt-in)。`screenshot_monitor_index`の既定値は`1`(`mss`の`monitors[0]`は全モニタ結合の仮想キャンバスになりがちなため、単一モニタを指す`1`を既定にする)。

### `src/shared/config/settings.py`(追加フィールド、静的・再起動要)

```python
azure_openai_api_version: str = "2024-08-01-preview"
intent_translation_model_name: str = "gpt-5.6-luna"
intent_translation_prompt: str = _DEFAULT_INTENT_TRANSLATION_PROMPT
```

`_DEFAULT_INTENT_TRANSLATION_PROMPT`は実機検証で確定した以下のシステムプロンプトをそのまま定数化する:

```
あなたの役割は、ユーザーの音声認識結果とその時点の画面スクリーンショットを基に、
別のコーディングエージェントへ送る依頼文プロンプトを作成することです。

対象特定の手順(この順序で必ず確認してください):
1. まず画面内のコードエディタのメインペイン(ソースコードが表示されている領域)を探してください。
2. その中で、背景色が周囲と異なる(反転・ハイライトされている)行や単語を探してください。これが
   ユーザーが選択操作中のテキストです。ステータスバーに "Ln xx, Col xx (n selected)" のような
   表示があれば、それも選択中である根拠として使ってください。
3. 選択されているテキストが含まれるファイル名・行番号・関数名やコード内容を具体的に読み取ってください。
   画面上部にファイルパスのパンくずリスト(breadcrumb)が表示されている場合は、それを使って
   対象ファイルの正確なパスを特定してください。
4. ユーザーの発話中の指示語(これ/ここ/それ/さっきの、等)は、上記2〜3で特定した選択中のコードを
   指すものとして解釈してください。
5. エラーダイアログ、通知ポップアップ、サイドバーのアイコンなど、選択中のコードと無関係に画面上に
   表示されているだけの要素は、指示語の対象として採用しないでください。
6. 画面のハイライト・選択状態は、あくまで「どの行・どの範囲が対象か」を特定するための内部的な
   手がかりとして使ってください。特定できた対象(行番号・関数名・コード内容)は、これまでと同じ
   精度で具体的に記述してください。禁止するのは「選択されている」「ハイライトされている」
   「カーソルがある」といったUI操作状態を表す言葉そのものを依頼文の文章内に書くことだけです。
   この言葉を避けるために、対象の行番号や範囲を広げたり曖昧にしたりしないでください。
   特定できているなら、その1行(または実際に選択されている範囲)だけを正確に指してください。
7. 生成する依頼文の範囲は、ユーザーの発話が実際に求めている内容に厳密に限定してください。発話に
   含まれていない追加の質問項目や作業内容(処理の流れの説明、特定の変数の役割への言及、等)を、
   親切心で勝手に付け加えないでください。ユーザーの発話が単純な質問であれば、依頼文も同程度
   シンプルにまとめてください。

重要な制約:
- あなた自身がユーザーの質問に回答したり、画面内容を調査・説明したりしてはいけません。
  あなたの出力は「次にコーディングエージェントへ渡す依頼文」そのものであり、回答ではありません。
- 発話内容が画面文脈の補完を必要としない(自己完結している)、または「えーっと」「あの」のような
  意味のあるタスクを含まないフィラー・言い淀みのみである場合は、新しい依頼文を作らず、
  音声認識結果の文章をそのまま(一字一句変更せず)出力してください。ユーザーが何も指示していないのに
  画面内容から推測して新たな依頼を作り出してはいけません。
- 出力は変換後の依頼文プロンプトのみとしてください。前置き・説明・見出し・コードブロックは一切
  付けず、1文の自然な疑問文または依頼文としてまとめてください。
```

### `src/containers.py`(DI配線)

```python
def _create_intent_translator(*, mai_api_key: str, mai_endpoint: str, deployment: str, api_version: str, prompt: str) -> AzureOpenAIIntentTranslator | None:
    if not mai_api_key or not mai_endpoint:
        return None
    return AzureOpenAIIntentTranslator(endpoint=mai_endpoint, api_key=mai_api_key, deployment=deployment, api_version=api_version, prompt=prompt)

# Provider定義
screenshot_capture = providers.Singleton(MssScreenshotCapturer)
segment_screenshot_pairer = providers.Singleton(SegmentScreenshotPairer, screenshot_capture=screenshot_capture, settings_repository=settings_repository)
intent_translator = providers.Singleton(_create_intent_translator, mai_api_key=secrets.provided.mai_api_key, mai_endpoint=secrets.provided.mai_endpoint, deployment=settings.provided.intent_translation_model_name, api_version=settings.provided.azure_openai_api_version, prompt=settings.provided.intent_translation_prompt)
intent_translation_use_case = providers.Singleton(IntentTranslationUseCase, translator=intent_translator, settings_repository=settings_repository)
intent_translation_dictation_adapter = providers.Singleton(IntentTranslationDictationAdapter, pairer=segment_screenshot_pairer, use_case=intent_translation_use_case)
```

既存の`audio_pipeline_coordinator`/`segment_accumulator`のProvider定義に`segment_lifecycle_hook=intent_translation_dictation_adapter`/`text_transform=intent_translation_dictation_adapter`を追加する。`secrets_loader.py`/`Secrets`は変更不要(`mai_api_key`/`mai_endpoint`をAzure OpenAI互換チャットにも流用する。コメントで「同一Azureリソースを STT とチャット補完の両方で使う」旨を一言追記する)。

### `src/templates/index.html`

- ステータスバーに校正トグルと同じ見た目のON/OFFトグルを追加。**校正トグル(`localStorage`のみ)とは異なり、`DynamicSettings.intent_translation_enabled`をサーバー側の真実源とする**(撮影の有無をサーバー側で判断する必要があるため)。クリック時は現在の`/api/settings`取得結果をベースに`intent_translation_enabled`だけ反転させ`PUT /api/settings`する(新規エンドポイントは追加しない)。
- `SETTINGS_FIELDS`配列に`screenshot_monitor_index`/`intent_translation_timeout_sec`の2項目を追加(`intent_translation_enabled`は専用トグルボタンのみで操作、フォームには出さない)。

### 依存関係

```
uv add openai
uv add mss
```

`pyproject.toml`の`[[tool.mypy.overrides]]`に`module = "mss.*"`の`ignore_missing_imports = true`を追加する(型スタブ未整備想定、`silero_vad`と同じ扱い)。

## 未解決課題への設計判断(確認済み・変更不要)

- **校正機能との関係**: 独立トグルとして両立可能にする。意図翻訳はセグメント確定時(`SegmentAccumulator.handle_event`)に先行実行され、校正はセッション終了時にフロントから`POST /api/proofread`で全文に対して追加で実行される。相互排他ロジックは追加しない。
  - **既知の副次課題(未対応・明示のみ)**: フロントの`session.text += data.text`は区切り文字なしで連結している。意図翻訳ONの場合、各セグメントが「1文の依頼文」として整形されるため、無音区切りが複数回発生すると完成した依頼文が区切りなく連結され読みにくくなる可能性がある。今回のプランでは対応しない。
- **撮影対象ディスプレイ**: `screenshot_monitor_index`設定1項目で対応、プラットフォーム分岐なし。マウス位置に応じた動的選択はスコープ外(ドキュメントの未指定事項として明記済み)。
- **プラットフォーム対応(Context §3の要件の具体化)**: `MssScreenshotCapturer`は`sys.platform`によるdarwin/other分岐を持たない単一実装とする。`AudioCapturePort`の`factory.py`(darwin→`PersistentStreamCapture`、other→`PerSessionStreamCapture`という戦略分岐)とは異なり、`pyperclip`が既にそうしているのと同じ「ライブラリ内部でOS差を吸収する単一実装」パターンに合わせる。`mss`はmacOS/Windows/Linux(X11)を公式にサポートしており、コード上はLinuxでも動作する想定だが、**このフェーズの動作検証はmacOS環境のみで行う**(Linux実機での確認はしない、Wayland環境では`mss`が信頼できるキャプチャ手段を持たない可能性が高いことが既知の制約として`docs/paste-latency-research.md`系のドキュメントに記載されているが、これも実機未検証)。Wayland等でキャプチャに失敗した場合は`capture()`が例外を捕捉して`None`を返し、意図翻訳がスキップされる(原文フォールバック、クラッシュしない)動作に留める。

## テスト方針

- **Application層**(新規): `tests/intent_translation/application/`に`test_segment_screenshot_pairer.py`(ON/OFF切替、`on_flush(produced_text=False)`で`_ready`に積まれないこと、FIFO順序、`reset`)、`test_intent_translation_use_case.py`(`ProofreadTextUseCase`のテストと対、`translator=None`/`enabled=False`/`screenshot=None`/成功/例外・タイムアウト時のフォールバック)、`test_dictation_hook_adapter.py`(委譲呼び出しの検証)。
- **既存Application層への追加**: `tests/dictation/application/test_audio_pipeline_coordinator.py`に、`segment_lifecycle_hook`のMagicMockを注入し、`start()`で`reset()`、発話開始検知(1回目のみ)で`on_speech_start()`、`_flush_segment`成功時に`on_flush(produced_text=True)`、認識結果が空(`stt_client.flush`が`""`を返す)場合は`on_flush(produced_text=False)`が呼ばれることを検証。`segment_lifecycle_hook=None`時に既存テストが全て通ることの回帰確認。`tests/dictation/application/test_segment_accumulator.py`にも同様に`text_transform`注入時/`None`時のテストを追加。
- **既存インフラのシグネチャ変更に伴うテスト修正**: `tests/dictation/application/test_recording_session_service.py:383`のインラインflushフェイクを`-> str`に変更し、既存の`SttEnginePort`利用箇所で戻り値の扱いが壊れていないか確認。`tests/dictation/infrastructure/stt/test_mai_transcribe_client.py`に`flush()`が認識テキストを返すこと/空文字列を返すことのテストを追加。
- **Infrastructure層**(新規): `test_mss_screenshot_capturer.py`(`@patch(".mss")`でモック、範囲外index、例外時`None`)、`test_azure_openai_intent_translator.py`(`max_completion_tokens`が使われること、空テキスト即返し、`content`空時のフォールバック)。実際のAzure通信は行わない。
- **DIコンテナ**: `tests/test_containers.py`に`test_intent_translator_is_none_without_mai_credentials`等、既存の`test_proofreader_is_none_without_vertex_credentials`と対になるテストを追加。
- **設定/Presentation層**: `tests/presentation/routes/test_settings_routes.py`の`test_returns_all_fields`は動的にフィールド集合を検査しているため無修正で新フィールドをカバーする。

## 検証手順

1. `uv run mypy` / `uv run ruff check` / `uv run pytest`(PostToolUse hookで自動実行されるが、モジュール新設のため`tests/intent_translation/`配下に`__init__.py`が正しく作られているか明示確認)。
2. `SttEnginePort.flush()`の戻り値変更が既存の全呼び出し箇所(`AudioPipelineCoordinator._flush_segment`のみ)で正しく扱われているか確認(mypy strictで型不整合が出れば即発覚するはず)。
3. 設計ドキュメントとの整合性確認: `docs/image_recognition_prompt.md`§5.6の未指定事項のうち、本プランで解決した項目(撮影間隔・撮影タイミング・保存方針・切替方法・タイムアウト・校正との関係)をドキュメントに反映するかどうかをユーザーに確認する(実装完了後)。
4. 統合レベルの確認observability: `intent_translation_enabled=True`かつ`mai_api_key`/`mai_endpoint`が有効な状態で実際に録音→発話→`recognized`イベントのテキストが依頼文形式に変換されていること、`intent_translation_enabled=False`または認証情報未設定時は生の認識結果がそのまま流れることを、開発環境で目視確認する(E2Eテストの自動実行はREADMEのポリシーに従いユーザー確認後)。
5. マルチセグメントのセッションで、2番目以降のセグメントが正しく対応するスクリーンショットとペアになっているか(意図的に無音のみのセグメントを1つ挟んだ場合でも後続セグメントの対応がずれないか)を目視確認する — 本プランの中核的なバグ修正(`produced_text`ガード)の妥当性を実データで裏付ける。
