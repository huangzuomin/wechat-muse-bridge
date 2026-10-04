# wechat-muse-bridge

Minimal Tencent ClawBot iLink transport adapter that forwards explicitly authorized direct text messages into the existing Muse Gadget Side Chat. Muse remains the only agent and decision center. This service does not expose a network listener, interpret intent, or control devices. Licensed under the [MIT License](LICENSE).

## Flow and limits

```text
WeChat ClawBot → Tencent iLink long poll → allowlist + text filter
  → musegadget send-user-msg (stdin) → Muse Side Chat
```

Supports direct-chat text, one or more explicitly allowlisted `from_user_id` values, `/reset`, persistent iLink cursor, and a single active Muse session. Group chats, other message types, missing sender IDs, and over-limit messages are ignored/rejected without delivery. The bridge does not send Muse responses back to WeChat.

Delivery is at-least-once oriented. The batch cursor is committed only after the full batch is processed. A Muse failure leaves the cursor uncommitted, so the batch is replayed; a bounded message-id cache and persisted IDs from an uncommitted batch suppress ordinary replay duplicates. Since `musegadget send-user-msg` has no idempotency key, a process crash in the narrow gap after Muse accepted a message and before state is saved can cause a duplicate.

## Phase 0 gate

Completed on Raspberry Pi 3B+ on 2026-10-04 before implementation:

| Case | Result |
| --- | --- |
| One message accepted | PASS, CLI exit 0 |
| Two messages to one session | PASS, both CLI exit 0 |
| Different session ID | PASS, CLI exit 0 |
| Gadget service stopped | PASS, CLI exit 1 with explicit socket error |
| Gadget restarted | PASS, service active and CLI exit 0 |
| Muse Side Chat visual check | PASS, same-session messages appeared together; separate session appeared separately |

The service-stop test briefly stopped `musegadget.service`; it was restarted and verified active.

## Requirements

- Raspberry Pi OS / Debian and Python 3.11 (Pi deployment target).
- Existing `musegadget` CLI and active `musegadget.service`, callable by the configured non-root service account. Ensure that account can access the Muse Gadget Unix socket.
- Outbound HTTPS to Tencent iLink and outbound Muse connectivity through `musegadget.service`.
- No inbound port, reverse proxy, tunnel, OpenClaw runtime, database, or message broker.

Python dependencies are `httpx` and `qrcode`; the rest uses the standard library.

## Install on Raspberry Pi

From the repository root on the development PC, copy the package to the Pi (replace `admin` and `pi-host` with your SSH account and host, or use your normal source deployment flow):

```bash
scp -r wechat-muse-bridge admin@pi-host:/tmp/
ssh admin@pi-host
cd /tmp/wechat-muse-bridge
sudo bash install-pi.sh
```

The installer defaults to the pre-existing `musebridge` service account and group. Set `SERVICE_USER` and `SERVICE_GROUP` through `sudo env` if Muse Gadget runs under another account or group; that account must already have CLI access and permission to reach Muse Gadget's Unix socket. For example: `sudo env SERVICE_USER=muse SERVICE_GROUP=muse bash install-pi.sh`.

The installer creates `/opt/wechat-muse-bridge/venv`, `/etc/wechat-muse-bridge/env`, and the configured `WECHAT_MUSE_DATA_DIR`, and installs the systemd unit with write access scoped to that data directory. It sets `MUSEGADGET_COMMAND` to the absolute executable path found for the service account. It leaves the production service disabled until an exact `from_user_id` is configured.

### Enroll the first WeChat account

No official WeChat account verification or public-account credentials are required. Obtain the exact Tencent iLink `from_user_id` with the interactive enrollment command. It completes QR login if needed, displays a short-lived one-time code, and waits up to five minutes for that exact direct text from the intended WeChat account. It prints only the sender ID; it never sends enrollment traffic to Muse.

Run as the service account configured in `systemd/wechat-muse-bridge.service` (`musebridge` by default), and make sure the production bridge is stopped so only one process polls this bot. The command refuses enrollment while the systemd service is active:

```bash
sudo systemctl stop wechat-muse-bridge
sudo -u musebridge /opt/wechat-muse-bridge/venv/bin/wechat-muse-bridge enroll --env-file /etc/wechat-muse-bridge/env
```

For a custom `SERVICE_USER`, replace `musebridge` in the command with that account.

Scan the displayed QR code in WeChat if prompted, then send the displayed one-time code to the ClawBot from the account to authorize. Treat the code as temporary and use it only from that account. Run enrollment during a quiet period: after a match, the iLink cursor for that update batch is saved, so unrelated messages in the same batch may be consumed. No enrollment message is forwarded to Muse.

Copy the exact `Enrolled from_user_id` value into the root-managed configuration, then start the production service:

```bash
sudo nano /etc/wechat-muse-bridge/env
sudo chmod 0640 /etc/wechat-muse-bridge/env
sudo chown root:musebridge /etc/wechat-muse-bridge/env
sudo systemctl enable --now wechat-muse-bridge
```

For a custom `SERVICE_GROUP`, use that group in the `chown` command.

If enrollment times out or the iLink login expires, run the enrollment command again. Credentials are saved after QR login; subsequent runs normally do not require rescanning. Check service health using:

```bash
systemctl status wechat-muse-bridge
journalctl -u wechat-muse-bridge
```

## Paths and permissions

| Data | Path | Owner/mode |
| --- | --- | --- |
| Application and venv | `/opt/wechat-muse-bridge` | root:root |
| Environment config / allowlist | `/etc/wechat-muse-bridge/env` | root:musebridge 0640 |
| iLink credentials | `/var/lib/wechat-muse-bridge/credentials.json` | musebridge, 0600 |
| Cursor and session state | `/var/lib/wechat-muse-bridge/state.json` | musebridge, 0600 |
| Logs | systemd journal | system managed |

Tokens and message bodies are excluded from logs. `DEBUG_PAYLOADS` is reserved and currently has no payload-logging implementation; keep it `false`.

## Commands and configuration

`/reset` rotates the persisted Muse session UUID. The next text message opens a fresh Muse Side Chat. The command itself is not forwarded.

Configuration is in `.env.example`. `ALLOWED_USER_IDS` is mandatory and fail-closed for the production service; the standalone `enroll` command is the only path allowed to run before the allowlist is set. `MAX_MESSAGE_CHARS` defaults to 8000. `MUSEGADGET_COMMAND` defaults to `musegadget` and accepts an executable plus fixed arguments; it is invoked without a shell and message content is sent over stdin.

Expired iLink auth (`ret` or `errcode` -14) stops polling and leaves the service in `needs-login` until an operator restarts it. This avoids a high-frequency authentication loop. Remove `/var/lib/wechat-muse-bridge/credentials.json` and restart the service to scan again:

```bash
sudo systemctl stop wechat-muse-bridge
sudo rm /var/lib/wechat-muse-bridge/credentials.json
sudo systemctl start wechat-muse-bridge
sudo journalctl -u wechat-muse-bridge -f
```

Network failures use exponential backoff up to 30 seconds. The cursor advances only after batch processing succeeds. IDs of messages successfully delivered before an in-batch failure are saved in the state file and cleared when the cursor commit succeeds.

## Version record

- Release history: see [CHANGELOG.md](CHANGELOG.md).
- Tencent protocol source/commit/channel version: see [PROTOCOL_BASELINE.md](PROTOCOL_BASELINE.md).
- Muse Gadget SDK: installed CLI and `send-user-msg` help were inspected on the Pi on 2026-10-04. The phase 0 cases above verified the ingress behavior. The installed package version was not available from the active CLI environment, so no version number is asserted.
- Python: Pi deployment target Python 3.11; the bridge package requires Python >=3.10.

## Development

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
```

See `tests/` for mocked protocol, filtering, cursor, credential, and Muse CLI coverage. Contributions should follow [CONTRIBUTING.md](CONTRIBUTING.md); security reports should follow [SECURITY.md](SECURITY.md).
