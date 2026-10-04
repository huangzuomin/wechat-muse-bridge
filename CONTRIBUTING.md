# Contributing

Thanks for helping improve `wechat-muse-bridge`.

## Development setup

Requires Python 3.10 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
```

Protocol changes should stay inside `src/wechat_muse_bridge/ilink/`. Update
`PROTOCOL_BASELINE.md` when changing the Tencent iLink reference, and add mocked
tests for new request and response behavior.

## Pull requests

- Keep message bodies, sender IDs, iLink credentials, and personal deployment
  details out of logs, fixtures, commits, and screenshots.
- Include tests for behavior changes and describe any Pi-specific verification.
- Outbound replies go through `wechat-muse-send`; keep recipient IDs and
  context tokens out of logs, fixtures, and commits.
