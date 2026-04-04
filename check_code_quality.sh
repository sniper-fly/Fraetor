#!/bin/bash

# コード品質チェックスクリプト
# 通常実行: 人間に読みやすい形式で出力
# --hooks オプション: Claude Code Hooks用のJSON形式で出力

HOOKS_MODE=false
if [ "$1" = "--hooks" ]; then
    HOOKS_MODE=true
fi

ERRORS=""
EXIT_STATUS=0


# ruff format
FORMAT_OUTPUT=$(uv run ruff format 2>&1)
FORMAT_STATUS=$?
if [ $FORMAT_STATUS -ne 0 ]; then
    ERRORS="${ERRORS}[ruff format error]\n${FORMAT_OUTPUT}\n\n"
    EXIT_STATUS=2
fi


# ruff check
CHECK_OUTPUT=$(uv run ruff check 2>&1)
CHECK_STATUS=$?
if [ $CHECK_STATUS -ne 0 ]; then
    ERRORS="${ERRORS}[ruff check error]\n${CHECK_OUTPUT}\n\n"
    EXIT_STATUS=2
fi


# mypy
MYPY_OUTPUT=$(uv run mypy 2>&1)
MYPY_STATUS=$?
if [ $MYPY_STATUS -ne 0 ]; then
    ERRORS="${ERRORS}[mypy error]\n${MYPY_OUTPUT}\n\n"
    EXIT_STATUS=2
fi


# pytest (コンパクト出力: 短縮トレースバック、ヘッダー省略)
PYTEST_OUTPUT=$(uv run pytest --tb=short --no-header -q 2>&1)
PYTEST_STATUS=$?
if [ $PYTEST_STATUS -ne 0 ]; then
    ERRORS="${ERRORS}[pytest error]\n${PYTEST_OUTPUT}\n\n"
    EXIT_STATUS=2
fi


# 結果出力
if [ $EXIT_STATUS -ne 0 ]; then
    if [ "$HOOKS_MODE" = true ]; then
        # --hooks オプション: JSON形式で出力（Claude Code Hooks用）
        ESCAPED_ERRORS=$(echo -e "$ERRORS" | jq -Rs .)
        cat <<EOF
{
  "decision": "block",
  "systemMessage": ${ESCAPED_ERRORS},
  "reason": "コード品質チェックに失敗しました。以下のエラーを確認してください。",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": ${ESCAPED_ERRORS}
  }
}
EOF
    else
        # 通常実行: 人間に読みやすい形式で出力
        echo "========================================="
        echo "コード品質チェックに失敗しました"
        echo "========================================="
        echo -e "$ERRORS"
    fi
else
    if [ "$HOOKS_MODE" = false ]; then
        echo "すべてのコード品質チェックに合格しました"
    fi
fi
