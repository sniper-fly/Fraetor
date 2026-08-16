# Herdr連携によるコピペ不要の送信 実装プラン

## Context

現状、文字起こし結果をコーディングエージェント (Claude Code等) に渡すには、確定後にクリップボードへコピーされたテキストを、対象のターミナル (Herdr管理下のペイン) を手動で選んでペーストする必要がある。この「貼り先を毎回選んでペーストする」手間を、録音停止と同時にHerdrのターミナルペインへ直接送信できるようにすることで解消する。

動機は「ショートカット一発運用」の維持であり、宛先選択のためにドロップダウン操作を毎回強制すると本来の目的に反する。そのため宛先確定は録音開始時点の「今前面に出ているHerdrペイン」を自動記録するデフォルト経路とし、手動選択・手動送信はそれを上書き/補完する経路として別に用意する。

対話で確定した要点 (変更しないこと):

| 論点 | 決定 |
|---|---|
| 新エンドポイント | 既存`/api/toggle-recording`とは別に`/api/toggle-recording-and-send-to-herdr`を新設。既存トグルは無関係のまま変更しない |
| 1回目呼び出し | Herdrの`focused_pane_id`を自動取得して記録 **かつ** 録音開始。取得失敗時は`None`のまま録音は開始する (エラーにしない) |
| 2回目呼び出し | 録音停止 **かつ** そのセッションを「送信確定」としてマークする (即時送信はしない) |
| 送信先の保持単位 | グローバル単一状態ではなくセッション (ブロック) 単位。後続録音で書き換わる誤送信事故を防ぐ |
| 実際の送信タイミング | 既存の校正フロー (`tryAdvanceQueue`が`/api/proofread`→`/api/finalize-session`を直列に呼ぶ既存フロー、変更しない) が完了した時点で、送信確定済みのブロックについて自動送信する |
| 校正タイムアウト時 | Herdr送信は諦め、失敗トーストを出しつつクリップボードへフォールバックする |
| 投入コマンド | `herdr agent prompt` (Enter送信込み) のみ。事前生存確認 (pane.get) はしない。実行結果 (成功/失敗) でフォールバック判定する |
| 送信失敗時 | 既存の`showCopyToast`と同型のトーストで通知し、クリップボードへフォールバックする |
| UI: メイン画面 | 未送信ブロックの直近4件を表示 (新しいものが上)。4件を超えると単純に表示対象から外れる (特別な状態遷移ではない) |
| 履歴 | 今まで通り全件を独立して表示し続ける (二重表示)。履歴内には手動送信ボタンを出さない |
| 各ブロックのUI | 個別の手動送信ボタン + 個別のドロップダウン (Herdrセッション選択・上書き用、デフォルトは自動取得値、開いた時に一覧取得) |
| 手動送信ボタンの状態 | 校正待ち中は無効化。校正完了後に有効化。`target_pane_id`が無い場合はクリップボードコピーとして動作する |
| セッション一覧取得契機 | ドロップダウンを開いた時に取得 |

## UIイメージ (メイン画面)

```
┌─────────────────────────────────────────────────┐
│ Voice Input                                      │
│ [メイン] [履歴] [設定]                            │
├─────────────────────────────────────────────────┤
│ 録音: ●停止中   校正: [ON]      📋  ⏻            │
├─────────────────────────────────────────────────┤
│ ┌─ ブロック1 (最新・録音中) ─────────────────┐  │
│ │ これはテスト録音です...(認識中)             │  │
│ │ [認識中の文字はグレー表示]                   │  │
│ │ 送信先: [🔽 w1:p1 (claude-code) ▼]  [送信]  │  │ ← 送信ボタンは校正待ち中は無効
│ └─────────────────────────────────────────────┘  │
│ ┌─ ブロック2 (校正済み・送信可能) ────────────┐  │
│ │ さっき喋った内容の確定テキストです。         │  │
│ │ 送信先: [🔽 w1:p2 (未選択)      ▼]  [送信]  │  │ ← 有効化済み、クリックで送信
│ └─────────────────────────────────────────────┘  │
│ ┌─ ブロック3 ──────────────────────────────────┐  │
│ │ さらに前に喋った内容...                       │  │
│ │ 送信先: [🔽 w2:p1 (別ペイン)    ▼]  [送信]  │  │
│ └─────────────────────────────────────────────┘  │
│ ┌─ ブロック4 (最古・もうすぐ表示から外れる) ───┐  │
│ │ 一番古い未送信ブロック                        │  │
│ │ 送信先: [🔽 未検出 (クリップボードのみ) ▼] [送信]│  │
│ └─────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘

[コピーしました / Herdr送信に失敗しました。クリップボードにコピーしました]
                  ↑ 画面下部に浮くトースト (既存のcopy-toastを再利用)
```

- 新しいものが上、古いものが下に並び、5件目が来ると一番下 (ブロック4相当) が表示から外れて履歴のみになる
- 各ブロックが個別にドロップダウン+送信ボタンを持つため、ブロック間で送信先が混線しない
- ドロップダウンはブロックが生まれた時点の`focused_pane_id`が自動選択済みの状態で表示され、開けば別セッションに変更できる
- 送信ボタンは、そのブロックの校正が完了するまで (または校正OFFなら文字起こし確定まで) 無効化表示になる
- Herdrトグル (新エンドポイント) の2回目が押されたブロックは、校正完了と同時に自動で送信ボタンと同じ処理が走る (手動操作不要)
- 履歴タブは今まで通り全ブロックを別途一覧表示するが、送信ボタン・ドロップダウンは出さない (コピー機能のみ)

## アーキテクチャ上の配置判断

Herdrクライアント (Socket API通信 + CLI呼び出し) は、既存の3境界づけられたコンテキスト (dictation/transcript_history/proofreading) のどれにも属さない**外部システムへのクライアント**である。これは`DynamicSettings`が「どの業務コンテキストにも属さない横断的関心事」として`src/shared/config/`に置かれた前例と同じ位置づけであり、同じパターンを踏襲して`src/shared/herdr/`に配置する。

**この配置により、`transcript_history`/`proofreading`モジュールへの変更は一切不要になる。** 送信の自動トリガーは既存の校正フロー完了を検知したフロントエンド (SSEイベント経由) が担い、`FinalizeSessionUseCase`(clipboard.copy/history.save) は今まで通り無条件・無関係に動作する。Herdr送信は完全に独立した並行アクションとして積む設計とする。

`dictation`モジュールへの変更は最小限 (`RecordingSession`へのフィールド追加、`RecordingSessionService`の2メソッドへのオプション引数追加) に留める。

## 1. `src/shared/herdr/`: Herdrクライアント (新設)

### 1.1 `ports.py`

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class HerdrSessionInfo(BaseModel):
    pane_id: str
    label: str

class HerdrClientPort(ABC):
    @abstractmethod
    async def get_focused_pane_id(self) -> str | None:
        """今前面に出ているペインIDを取得する。取得できない場合は None (例外を投げない)。"""

    @abstractmethod
    async def list_sessions(self) -> list[HerdrSessionInfo]:
        """選択UI表示用のセッション一覧。取得できない場合は空リスト。"""

    @abstractmethod
    async def send_text(self, pane_id: str, text: str) -> bool:
        """テキストを投入する。成功/失敗を bool で返す (例外を投げない)。"""
```

### 1.2 `socket_client.py`: `HerdrSocketClient(HerdrClientPort)`

- ソケットパス解決: `HERDR_SOCKET_PATH`環境変数 → `HERDR_SESSION`環境変数 (`~/.config/herdr/sessions/<name>/herdr.sock`) → デフォルト`~/.config/herdr/herdr.sock`。Fraetorサーバーがherdrペイン内で起動されない可能性があるため、環境変数への依存を前提にしない (未設定でもデフォルトパスで動作する)
- テスト容易性のため、`__init__(self, socket_path: Path | None = None)`でパスを注入可能にする (省略時は上記解決ロジックを使う)
- `_call(method, params)`: ソケットファイル不在なら即`None`。`asyncio.open_unix_connection`で接続 (タイムアウト2秒)、newline-delimited JSON `{"id": "req_1", "method": ..., "params": ...}`を書き込み、1行読んで`json.loads`。`OSError`/`TimeoutError`/`JSONDecodeError`は全て捕捉しログのみ出し`None`を返す (呼び出し元に例外を伝播させない)
- `get_focused_pane_id()`: `session.snapshot`を呼び、`result.focused_pane_id`を返す
- `list_sessions()`: `pane.list`を呼び、`result.panes`を`HerdrSessionInfo`に変換する。**注意: `pane.list`レスポンスの正確なフィールド名 (`pane_id`か`id`か、ラベルに使う項目) は実装時にHerdr公式ドキュメント/実機で再確認すること。要件定義書の記述からの推測であり未確認**
- `send_text(pane_id, text)`: `asyncio.create_subprocess_exec("herdr", "agent", "prompt", pane_id, text)`。`FileNotFoundError`/`OSError`捕捉、`returncode != 0`ならログ+`False`、成功で`True`

### 1.3 テスト観点 (`tests/shared/herdr/test_socket_client.py`)

- `asyncio.start_unix_server`でテスト用の一時ソケットサーバーを立て、`socket_path`に注入。`session.snapshot`への応答から`get_focused_pane_id`が正しく`focused_pane_id`を抜き出すこと
- ソケットファイルが存在しない場合、`get_focused_pane_id`/`list_sessions`が例外を出さず`None`/`[]`を返すこと
- `list_sessions`が`pane.list`応答を`HerdrSessionInfo`のリストに変換すること
- `send_text`: `asyncio.create_subprocess_exec`をモンキーパッチし、returncode 0で`True`、非0で`False`、`FileNotFoundError`発生時も例外を伝播せず`False`を返すこと

## 2. `dictation`モジュールの変更

### 2.1 `RecordingSession`(`src/dictation/domain/models.py:14-23`)

`target_pane_id: str | None = None`フィールドを追加する。

### 2.2 `RecordingSessionService`(`src/dictation/application/recording_session_service.py`)

- `start_session()`(51行目〜)に`*, target_pane_id: str | None = None, herdr_requested: bool = False`を追加。`RecordingSession`構築時に`target_pane_id=target_pane_id`を渡し、89-91行目のbroadcastを`{"recording": True, "session_id": session.id, "target_pane_id": target_pane_id, "herdr_requested": herdr_requested}`に拡張する
- `stop_session()`(102行目〜)に`herdr_send_confirmed: bool = False`を追加。137行目のbroadcastを`{"recording": False, "session_id": recording_session.id if recording_session else None, "herdr_send_confirmed": herdr_send_confirmed}`に拡張する (`recording_session`変数は123行目で既に取得済みのものを使う)

いずれも既存呼び出し (`/api/toggle-recording`、デフォルト引数のまま) は無変更で動作する。SSEペイロードへの追加フィールドは既存フロントエンドの`JSON.parse(e.data)`ハンドラに影響しない (未知フィールドは無視される)。

### 2.3 テスト観点 (`tests/dictation/application/test_recording_session_service.py`への追加)

- `start_session(target_pane_id="w1:p1", herdr_requested=True)`で生成される`RecordingSession.target_pane_id`が正しいこと、broadcastされる`status`イベントに`target_pane_id`/`herdr_requested`が含まれること
- `stop_session(herdr_send_confirmed=True)`のbroadcastに`session_id`/`herdr_send_confirmed`が含まれること
- 既存の引数なし呼び出しの挙動 (broadcast内容含む) が変わらないこと (回帰確認)

## 3. 新規ルート `src/presentation/routes/herdr_routes.py`

```python
@router.post("/api/toggle-recording-and-send-to-herdr")
async def toggle_recording_and_send_to_herdr(request: Request) -> dict[str, object]:
    app_state: AppState = request.app.state.app_state
    recording_session_service: RecordingSessionService = request.app.state.recording_session_service
    herdr_client: HerdrClientPort = request.app.state.herdr_client

    if app_state.recording:
        await recording_session_service.stop_session(herdr_send_confirmed=True)
        return {"recording": False}

    target_pane_id = await herdr_client.get_focused_pane_id()
    await recording_session_service.start_session(target_pane_id=target_pane_id, herdr_requested=True)
    return {"recording": True, "target_pane_id": target_pane_id}


@router.get("/api/herdr-sessions")
async def list_herdr_sessions(request: Request) -> list[dict[str, str]]:
    herdr_client: HerdrClientPort = request.app.state.herdr_client
    sessions = await herdr_client.list_sessions()
    return [s.model_dump() for s in sessions]


@router.post("/api/send-to-herdr")
async def send_to_herdr(request: Request) -> dict[str, bool]:
    herdr_client: HerdrClientPort = request.app.state.herdr_client
    body = SendToHerdrRequest.model_validate(await request.json())
    success = await herdr_client.send_text(body.pane_id, body.text)
    return {"success": success}
```

`SendToHerdrRequest(pane_id: str, text: str)`を`src/presentation/schemas/request_models.py`に追加する (既存の`FinalizeSessionRequest`/`ProofreadRequest`と同じ場所)。

**このエンドポイントはブラウザのJSから直接叩かれない。** 既存の`/api/toggle-recording`と同じく、外部のショートカットスクリプト (§5) からcurlで叩かれる。フロントエンドはHTTPレスポンスを受け取れないため、必要な情報は全てSSEの`status`イベント経由で受け取る設計にしている (§2.2)。`/api/herdr-sessions`と`/api/send-to-herdr`はブラウザJSから直接叩く。

### 3.1 テスト観点 (`tests/presentation/test_herdr_routes.py`)

- フェイクの`HerdrClientPort`実装を`app.state.herdr_client`に注入し、TestClient経由で3エンドポイントを検証する
- 1回目の呼び出しで`start_session`が`target_pane_id`付きで呼ばれること、`focused_pane_id`取得失敗 (`None`) でもエラーにならず録音が開始されること
- 2回目の呼び出しで`stop_session(herdr_send_confirmed=True)`が呼ばれること
- `/api/herdr-sessions`がポートの返り値をそのままJSON化すること
- `/api/send-to-herdr`がポートの`send_text`結果をそのまま`success`として返すこと

## 4. `containers.py`/`app.py`の配線

`containers.py`:
```python
from src.shared.herdr.socket_client import HerdrSocketClient
...
herdr_client: providers.Provider[HerdrClientPort] = providers.Singleton(HerdrSocketClient)
```

`app.py`の`_build_lifespan`(39-71行目)に`app.state.herdr_client = container.herdr_client()`を追加し、`create_app`(74-92行目)で`app.include_router(herdr_routes.router)`を追加する。

## 5. 新規ショートカットスクリプト `toggle-recording-and-send-to-herdr.sh`

既存`toggle-recording.sh`と同一のサーバー起動・ヘルスチェック処理を複製し、最後のcurl行のみ`/api/toggle-recording-and-send-to-herdr`に向ける。既存スクリプトとの共通化 (関数抽出等) は行わない — 既存スクリプト自体が単一ファイルの薄いシェルスクリプトであり、この規模で共通化する価値がないため既存パターンをそのまま踏襲する。

## 6. フロントエンド (`src/templates/index.html`)

### 6.1 `sessionQueue`アイテムの拡張

各要素に以下を追加する: `finalized: boolean` (校正+finalize-session完了フラグ、新設)、`herdrRequested: boolean`、`herdrSendConfirmed: boolean`、`herdrAutoSendAttempted: boolean` (二重送信防止)、`targetPaneId: string | null`、`selectedPaneId: string | null` (ドロップダウンでの上書き値、デフォルトは`targetPaneId`)、`proofreadSucceeded: boolean` (デフォルト`true`)。

`getOrCreateSession(id, opts)`(213-220行目)を拡張し、`opts.targetPaneId`/`opts.herdrRequested`を初期値に反映する。

### 6.2 `status`イベントハンドラの拡張 (300-307行目)

- 開始時 (`data.recording === true`): `getOrCreateSession(data.session_id, {targetPaneId: data.target_pane_id, herdrRequested: data.herdr_requested})`
- 停止時 (`data.recording === false`): `data.herdr_send_confirmed`が真なら、対応する`sessionQueue`アイテムの`herdrSendConfirmed = true`にし、`maybeAutoSendToHerdr(session)`を呼ぶ (まだ`finalized`でなければ関数内で早期returnし、`tryAdvanceQueue`側の完了時にも同じ関数を呼ぶことで確実に発火させる)

### 6.3 `tryAdvanceQueue`の変更 (229-264行目)

- **重複処理バグの回避**: 「先頭を必ずshiftする」既存前提を崩すため、`sessionQueue[0]`固定ではなく`sessionQueue.find(s => !s.finalized)`を処理対象にする (未finalizedの先頭)
- 校正API呼び出し (238-253行目) のレスポンス受信時、`front.proofreadSucceeded = data.proofread`を保存する。`catch`ブロック (249-251行目、ネットワーク失敗) でも`front.proofreadSucceeded = false`とする
- `/api/finalize-session`呼び出し後、`sessionQueue.shift()`を**削除**し、代わりに`front.finalized = true`を設定。`front.herdrRequested`が真なら`await maybeAutoSendToHerdr(front)`を呼ぶ
- 末尾に`evictOldBlocks()`(新設、§6.4) と`renderBlocks()`(新設、§6.5) を呼ぶ

### 6.4 表示件数の上限と退避

```js
let maxBlocks = 4; // ページ読み込み時に /api/settings の herdr_slot_count で上書きする

function evictOldBlocks() {
  while (sessionQueue.length > maxBlocks && sessionQueue[0].finalized) {
    sessionQueue.shift();
  }
}
```

一度も録音していない状態で最大4件までしか同時に「未finalized」になり得ない前提 (録音は同時に1件しか走らないため) により、finalized済みの古いものだけが安全に退避される。

### 6.5 複数ブロック表示への書き換え

現状の単一`#editor-textarea`/`#editor-interim`(50-55行目)を、`renderBlocks()`が動的に生成する最大4件のブロック (各ブロックに`textarea` + interim表示 + Herdrセッション選択`select` + 送信ボタン) に置き換える。

- `renderBlocks()`: `[...sessionQueue].slice(-maxBlocks).reverse()`(新しいものが上) をブロックHTMLとして`#blocks-container`(新設のコンテナ要素、`#editor-mode`を置き換える) にレンダリングする
- 既存の`ensureDisplaying`/`appendToTextarea`/`updateEditorInterim`は単一要素決め打ちの実装のため、対象要素をセッションIDから引く形 (`document.getElementById('block-textarea-' + session.id)`等) に書き換える。`recognized`/`interim`/`processing`系のSSEハンドラ (269-298行目) も同様に、`sessionQueue[0]`固定の参照をセッションID一致判定に変える (現状既に`data.session_id`で該当セッションを特定しているため、表示更新先をそのセッション用のDOM要素に向けるだけで済む)
- 各ブロックの送信ボタン: `front.finalized`が真になるまで`disabled`。クリックで`manualSendBlock(session.id)`を呼ぶ
- 各ブロックのドロップダウン: `onfocus`/`onclick`で一度だけ`/api/herdr-sessions`を取得し`<option>`を生成 (キャッシュせず開くたび取得、既存決定に従う)。選択変更で該当セッションの`selectedPaneId`を更新する

### 6.6 送信ロジック (新設関数)

```js
function showToast(message, isError = false) {
  const toast = document.getElementById('copy-toast');
  toast.textContent = message;
  toast.classList.toggle('text-red-300', isError);
  toast.classList.remove('opacity-0');
  clearTimeout(copyToastTimeoutId);
  copyToastTimeoutId = setTimeout(() => toast.classList.add('opacity-0'), 1500);
}

async function copyToClipboard(text, message = 'コピーしました') {
  try {
    await navigator.clipboard.writeText(text);
    showToast(message);
  } catch {
    // クリップボードアクセス不可時は何もしない
  }
}

async function sendToHerdrOrFallback(paneId, text) {
  if (!paneId) {
    await copyToClipboard(text, 'Herdr未検出のためクリップボードにコピーしました');
    return;
  }
  try {
    const res = await fetch('/api/send-to-herdr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pane_id: paneId, text }),
    });
    const data = await res.json();
    if (!data.success) throw new Error('send failed');
  } catch {
    await copyToClipboard(text, 'Herdr送信に失敗しました。クリップボードにコピーしました');
  }
}

async function maybeAutoSendToHerdr(session) {
  if (!session.herdrRequested || !session.herdrSendConfirmed || !session.finalized) return;
  if (session.herdrAutoSendAttempted) return;
  session.herdrAutoSendAttempted = true;
  if (!session.proofreadSucceeded) {
    await copyToClipboard(session.text, '校正がタイムアウトしたため送信を中止し、クリップボードにコピーしました');
    return;
  }
  await sendToHerdrOrFallback(session.targetPaneId, session.text);
}

async function manualSendBlock(sessionId) {
  const session = sessionQueue.find(s => s.id === sessionId);
  if (!session) return;
  await sendToHerdrOrFallback(session.selectedPaneId ?? session.targetPaneId, session.text);
}
```

既存の`showCopyToast()`は`showToast(message)`に一般化し、`copyMainText()`/`copyHistoryCard()`の呼び出しは変更不要 (デフォルト引数`'コピーしました'`が既存動作を保つ)。

### 6.7 表示件数の設定値化

`src/shared/config/dynamic_settings.py`の`DynamicSettings`に`herdr_slot_count: int = 4`を追加する。既存の`SETTINGS_FIELDS`(index.html:387-398)配列に`{ key: 'herdr_slot_count', label: 'Herdr表示ブロック数', unit: '件', step: '1' }`を追加すれば、既存の汎用設定フォーム生成ロジックがそのまま対応する。ページ読み込み時 (`connectSSE()`呼び出し付近) に`/api/settings`を1回取得し`maxBlocks`を初期化する処理を追加する。既存の設定システムに乗せるだけで追加コストが低いため、固定値ではなく設定化する。

## 7. 実装順序

1. `src/shared/herdr/ports.py`/`socket_client.py` + テスト (§1)
2. `RecordingSession.target_pane_id`追加、`RecordingSessionService`の2メソッド拡張 + テスト (§2)
3. `DynamicSettings.herdr_slot_count`追加 (§6.7)
4. `containers.py`/`app.py`の配線 (§4)
5. `herdr_routes.py` + `SendToHerdrRequest` + テスト (§3)
6. `toggle-recording-and-send-to-herdr.sh`(§5)
7. フロントエンド: `sessionQueue`拡張・`tryAdvanceQueue`の重複処理修正・`status`ハンドラ拡張 (§6.1-6.3)
8. フロントエンド: 複数ブロック表示・送信ロジック・トースト一般化 (§6.4-6.6)
9. `design.md`にHerdr送信経路 (新たな出力先) を追記する

## 8. 検証手順

### 8.1 自動テスト (PostToolUse hookで実行)

- 各セクションの「テスト観点」を実装する

### 8.2 設計レベル・統合レベルの観点

- **設計ドキュメントとの整合性**: `design.md`更新 (§7-9) を実施する
- **既存アーキテクチャとの整合性**: `shared/herdr/`が既存の`shared/config/`と同型のports.py+実装ファイル構成になっていること、Presentation層 (`herdr_routes.py`) がInfrastructure具象を直接importしていないこと (import-linter契約)
- **既存の「セッション単位の状態管理」パターンとの一貫性**: `target_pane_id`をグローバル状態でなくセッション単位で保持する設計が、既存の`RecordingSession`/`sessionQueue`アイテム単位の状態管理と一致していること
- **既存の校正フローとの非破壊性**: `tryAdvanceQueue`の`shift()`削除+`find(!finalized)`化が、Herdr機能を全く使わない既存ユーザー (校正ON/OFFいずれも) の動作 (逐次確定・クリップボードコピー・履歴保存) を変えていないことを確認する (回帰確認)
- **二重送信・二重トーストの防止**: `herdrAutoSendAttempted`フラグにより、SSE再接続時の`status`イベント再送や`maybeAutoSendToHerdr`の複数箇所からの呼び出しで送信が重複しないこと

### 8.3 手動確認 (ユーザーへの確認が必要)

- 実際のHerdr環境 (`HERDR_ENV=1`のペイン内、または別途起動したHerdrインスタンス) を使い、以下を確認する:
  - `focused_pane_id`の自動取得→録音→送信確定→校正完了後に対象ペインへ実際にテキストが投入されEnterまで送信されること
  - Herdr未起動時に1回目呼び出しでもエラーにならず録音が開始され、送信時にクリップボードへフォールバック+トーストが出ること
  - 複数回連続して録音した際、4件を超えた古いブロックが表示から外れ履歴のみになること、各ブロックの送信先が混線しないこと
  - ドロップダウンでの手動選択上書き、手動送信ボタンでの送信が動作すること
- ブラウザでのUI確認 (`run`スキル等でdev server起動し、複数ブロック表示・ドロップダウン・トーストを目視確認)
- E2Eテスト (`tests/e2e/`) は実クラウド通信を伴うため、一区切りのタイミングでユーザーに実行可否を確認する (今回のプランでは新規E2E追加は行わない)

## 9. 未確認事項 (実装時に検証が必要)

- `pane.list`のレスポンス正確なフィールド名 (§1.2)。Herdr公式ドキュメント/実機で実装時に確認する
