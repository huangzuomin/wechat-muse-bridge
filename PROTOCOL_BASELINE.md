# Protocol baseline

- Upstream: `Tencent/openclaw-weixin`
- Reference: [`docs/protocol.md`](https://github.com/Tencent/openclaw-weixin/blob/24de5c9eb0dd5e595d7e2d090ed8a3f82870d42c/docs/protocol.md)
- Commit: `24de5c9eb0dd5e595d7e2d090ed8a3f82870d42c`
- Commit date: 2026-09-21
- Protocol `base_info.channel_version`: `2.4.8`
- Bridge baseline recorded: 2026-10-04

The upstream documentation says client behavior and types are not a permanent or complete server contract. Tencent-specific request and response shapes stay inside `wechat_muse_bridge.ilink`. Review upstream changes before updating this baseline; protocol adaptations should remain inside `ilink/`.
