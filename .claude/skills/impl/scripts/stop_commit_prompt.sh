#!/bin/bash
set -euo pipefail

INPUT=$(cat)

# 無限ループ防止
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active')
if [ "$STOP_ACTIVE" = "true" ]; then
  exit 0
fi

CWD=$(echo "$INPUT" | jq -r '.cwd')
cd "$CWD"

# git リポジトリでなければ何もしない
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exit 0
fi

# 変更がなければ何もしない
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  exit 0
fi

# 変更がある場合、コミットを促すメッセージを表示してブロック
jq -n '{
  decision: "block",
  reason: "未コミットの変更があります。変更を git add してコミットしてください。"
}'
