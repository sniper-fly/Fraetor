---
name: impl
description: impl ToDo
disable-model-invocation: true
hooks:
  Stop:
    - hooks:
      - type: command
        command: "bash .claude/skills/impl/scripts/stop_commit_prompt.sh"
---
@design.md を背景情報として
@todo.md の $0 を実装せよ
