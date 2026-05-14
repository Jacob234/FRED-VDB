---
name: block-fred-key-leak
enabled: true
event: file
action: block
conditions:
  - field: content
    operator: regex_match
    pattern: \b[a-f0-9]{32}\b
  - field: content
    operator: regex_match
    pattern: (?i)fred[_-]?api[_-]?key
---

**Refusing to write a FRED-API-key-shaped value.**

This file's new content contains both a 32-character lowercase hex token
(the exact shape of a FRED API key) AND a reference to `FRED_API_KEY` /
`fred_api_key`. That combination matches the failure mode that leaked the
live key in commit `2eed6b5` (`.planning/codebase/CONCERNS.md`).

**If this is intentional documentation** that needs to discuss the key
value:
- Redact it: `<REDACTED>`, or show only a prefix like `f0521…`
- Or reference the env-var name: `$FRED_API_KEY` (not the literal)

**If this is a true false positive** — for example, an MD5 / 32-hex hash
that legitimately needs to appear in a file that also mentions
`FRED_API_KEY` — temporarily disable this rule:
1. Edit `.claude/hookify.block-fred-key-leak.local.md`
2. Set `enabled: false` in the frontmatter
3. Make the write
4. Re-enable the rule

**Defense in depth**: `.gitleaks.toml` (run by pre-commit) provides a
second layer at commit time. This hook stops the value before it reaches
disk; gitleaks stops it before it reaches git.
