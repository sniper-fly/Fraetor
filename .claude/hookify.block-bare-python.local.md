---
name: block-bare-python
enabled: true
event: bash
pattern: ^python\s
action: block
---

**Direct use of `python` command is blocked.**

Use `uv run` in this project.
