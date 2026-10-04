# Changelog

## 0.2.0 - 2026-10-04

- Add the outbound leg: `wechat-muse-send` CLI pushes Muse replies back to WeChat via iLink `sendmessage` (stdin or args, paragraph chunking, widget-token stripping).
- Inbound loop now captures `reply_to_user_id` / `reply_context_token` per accepted message for outbound addressing (token only overwritten when present).
- Bridge is now two-way; verified end-to-end on Raspberry Pi (WeChat → Muse → WeChat round trip).

## 0.1.0 - 2026-10-04

- Initial public release of the WeChat Tencent iLink to Muse Gadget bridge.
- Add allowlisted direct-text forwarding, private credential and cursor state, one-time sender enrollment, and a Raspberry Pi systemd installer.
- Document the one-way message flow, delivery behavior, security boundaries, and tested Raspberry Pi deployment assumptions.
