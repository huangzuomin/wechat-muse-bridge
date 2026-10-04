# wechat-muse-bridge

一个连接微信与现有 Muse Gadget Side Chat 的轻量腾讯 ClawBot iLink 桥接服务。入站方向：将明确授权的单聊文本转发到 Muse。出站方向（v0.2.0）：通过 `wechat-muse-send` 将 Muse 回复发回微信。Muse 仍是唯一的智能体和决策中心。本服务不开放网络监听端口、不解释用户意图，也不控制设备。采用 [MIT 许可证](LICENSE)。

[English](README.md) | 简体中文

## 消息流与限制

```text
入站：微信 ClawBot → 腾讯 iLink 长轮询 → allowlist 与文本过滤
         → musegadget send-user-msg（stdin）→ Muse Side Chat
出站：Muse 回复 → wechat-muse-send（stdin/参数）→ iLink sendmessage → 微信
```

支持单聊文本、一个或多个明确加入 allowlist 的 `from_user_id`、`/reset`、持久化 iLink cursor，以及单个活跃 Muse 会话。群聊、其他消息类型、缺少 sender ID 的消息和超出长度限制的消息不会被转发。

出站寻址：入站循环会把最近一条已授权消息的发送者 `from_user_id` 和 `context_token` 保存到状态文件。通常无需手动指定收件人：

```bash
echo "回复内容" | /opt/wechat-muse-bridge/venv/bin/wechat-muse-send
# 或：wechat-muse-send --to-user-id ID --context-token TOKEN "回复内容"
```

长回复会按段落边界拆分，每段最多 4000 个字符。Muse 聊天窗口部件标记（`[[hatch_widget:…]]`）会被移除，因为微信无法显示这类内容。出站发送要求至少有一条先前的入站消息用于记录收件人；否则命令会以状态码 1 退出。

消息投递采用至少一次语义。只有整批消息处理完成后才提交批次 cursor；Muse 调用失败时 cursor 不前进，之后会重放该批次。有限长度的消息 ID 缓存和持久化的未提交批次消息 ID 可抑制常见的重放重复。由于 `musegadget send-user-msg` 不支持幂等键，如果进程恰好在 Muse 接收消息、但状态尚未保存的短暂间隙崩溃，消息仍可能重复。

## Phase 0 验收

实现前已于 2026-10-04 在 Raspberry Pi 3B+ 完成：

| 场景 | 结果 |
| --- | --- |
| 单条消息成功发送 | 通过，CLI 退出码 0 |
| 向同一会话发送两条消息 | 通过，两次 CLI 均退出码 0 |
| 使用不同会话 ID | 通过，CLI 退出码 0 |
| 停止 Gadget 服务 | 通过，CLI 退出码 1 并显示明确的 socket 错误 |
| 重启 Gadget 服务 | 通过，服务恢复运行且 CLI 退出码 0 |
| Muse Side Chat 界面检查 | 通过，同会话消息显示在一起，不同会话彼此分开 |

停止服务的测试曾短暂停止 `musegadget.service`；测试后已重启并确认服务运行正常。

## 运行要求

- Raspberry Pi OS / Debian；Pi 部署目标为 Python 3.11。
- 已安装 `musegadget` CLI，且 `musegadget.service` 正常运行。配置的非 root 服务账户必须能调用 CLI 并访问 Muse Gadget Unix socket。
- 可通过出站 HTTPS 访问腾讯 iLink，并能通过 `musegadget.service` 连接 Muse。
- 无需开放入站端口、反向代理、隧道、OpenClaw 运行环境、数据库或消息代理。

Python 依赖为 `httpx` 和 `qrcode`，其余使用 Python 标准库。

## 在 Raspberry Pi 上安装

在开发电脑的仓库根目录执行以下命令，将项目复制到 Pi（请替换 `admin` 和 `pi-host`，也可以使用现有的代码部署方式）：

```bash
scp -r wechat-muse-bridge admin@pi-host:/tmp/
ssh admin@pi-host
cd /tmp/wechat-muse-bridge
sudo bash install-pi.sh
```

安装器默认使用预先创建的 `musebridge` 服务账户和用户组。如果 Muse Gadget 由其他账户或用户组运行，可通过 `sudo env` 设置 `SERVICE_USER` 和 `SERVICE_GROUP`。该账户必须已有 CLI 使用权限，并能访问 Muse Gadget Unix socket。例如：`sudo env SERVICE_USER=muse SERVICE_GROUP=muse bash install-pi.sh`。

安装器会创建 `/opt/wechat-muse-bridge/venv`、`/etc/wechat-muse-bridge/env` 和配置的 `WECHAT_MUSE_DATA_DIR`，并安装 systemd unit，将可写权限限制在该数据目录。它会把服务账户解析到的 `musegadget` 绝对路径写入配置。只有配置好准确的 `from_user_id` 后，才能启用正式服务。

### 登记首个微信账号

无需认证微信公众号，也不需要公众号凭据。使用交互式登记命令取得准确的腾讯 iLink `from_user_id`。如有需要，命令会先完成二维码登录，然后显示一个短时有效的一次性口令，并等待最多五分钟，直到目标微信账号发送该单聊文本。命令只输出 sender ID，不会把登记期间的消息发送给 Muse。

请使用 `systemd/wechat-muse-bridge.service` 中配置的服务账户运行（默认是 `musebridge`），并先停止正式桥接服务，确保同一时间只有一个进程轮询此 bot。systemd 服务处于运行状态时，登记命令会拒绝继续：

```bash
sudo systemctl stop wechat-muse-bridge
sudo -u musebridge /opt/wechat-muse-bridge/venv/bin/wechat-muse-bridge enroll --env-file /etc/wechat-muse-bridge/env
```

如果使用自定义 `SERVICE_USER`，请将命令中的 `musebridge` 替换为该账户。

如终端提示，请在微信中扫描二维码。然后从准备授权的微信账号向 ClawBot 发送终端显示的一次性口令。该口令仅供临时使用，且只能由该账号发送。请在安静时段登记：匹配成功后会保存该条更新所在批次的 iLink cursor，因此同一批次中的其他消息可能被消费。登记消息不会转发给 Muse。

将终端显示的 `Enrolled from_user_id` 精确值写入 root 管理的配置文件，然后启动正式服务：

```bash
sudo nano /etc/wechat-muse-bridge/env
sudo chmod 0640 /etc/wechat-muse-bridge/env
sudo chown root:musebridge /etc/wechat-muse-bridge/env
sudo systemctl enable --now wechat-muse-bridge
```

如果使用了自定义 `SERVICE_GROUP`，请在 `chown` 命令中使用对应的用户组。

若登记超时或 iLink 登录过期，请重新运行登记命令。二维码登录成功后会保存凭据，之后一般无需再次扫码。可用以下命令检查服务状态：

```bash
systemctl status wechat-muse-bridge
journalctl -u wechat-muse-bridge
```

## 文件路径与权限

| 数据 | 路径 | 所有者/权限 |
| --- | --- | --- |
| 应用与虚拟环境 | `/opt/wechat-muse-bridge` | root:root |
| 环境配置 / allowlist | `/etc/wechat-muse-bridge/env` | root:musebridge 0640 |
| iLink 凭据 | `/var/lib/wechat-muse-bridge/credentials.json` | musebridge，0600 |
| cursor 与会话状态 | `/var/lib/wechat-muse-bridge/state.json` | musebridge，0600 |
| 日志 | systemd journal | 由 systemd 管理 |

日志不会记录 token 或消息正文。`DEBUG_PAYLOADS` 是保留配置项，目前没有对应的 payload 日志实现；请保持为 `false`。

## 命令与配置

`/reset` 会轮换持久化的 Muse session UUID。下一条文本消息会开启新的 Muse Side Chat；`/reset` 本身不会被转发。

配置项见 `.env.example`。正式服务必须设置非空的 `ALLOWED_USER_IDS`，并采用 fail-closed 策略；在 allowlist 尚未配置前，只能运行独立的 `enroll` 命令。`MAX_MESSAGE_CHARS` 默认值为 8000。`MUSEGADGET_COMMAND` 默认是 `musegadget`，也可设置可执行文件及固定参数；服务不会通过 shell 调用它，并通过 stdin 传递消息正文。

如果 iLink 认证过期（`ret` 或 `errcode` 为 -14），服务会停止轮询并保持在需要重新登录的状态，直到操作员重启服务，避免高频认证重试。若要重新扫码，请先删除 `/var/lib/wechat-muse-bridge/credentials.json`，然后重启服务：

```bash
sudo systemctl stop wechat-muse-bridge
sudo rm /var/lib/wechat-muse-bridge/credentials.json
sudo systemctl start wechat-muse-bridge
sudo journalctl -u wechat-muse-bridge -f
```

网络失败时采用指数退避，最长 30 秒。只有整批消息处理完成后 cursor 才会前进。在同一批次中，如果部分消息已成功送达 Muse 后发生失败，这些消息 ID 会先写入状态文件；cursor 提交成功后再清除这些 ID。

## 版本记录

- 发布历史：见 [CHANGELOG.md](CHANGELOG.md)。
- 腾讯协议来源、commit 和 channel 版本：见 [PROTOCOL_BASELINE.md](PROTOCOL_BASELINE.md)。
- Muse Gadget SDK：2026-10-04 在 Pi 上检查了已安装的 CLI 和 `send-user-msg` 帮助信息；上方 Phase 0 场景验证了入站行为。当前 CLI 环境无法读取已安装软件包的版本，因此不声明具体版本号。
- Python：Pi 部署目标为 Python 3.11；桥接包要求 Python >=3.10。

## 开发

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
```

`tests/` 包含协议模拟、消息过滤、cursor、凭据和 Muse CLI 等测试。贡献请遵循 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按 [SECURITY.md](SECURITY.md) 指引报告。
