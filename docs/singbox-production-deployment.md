# sing-box 生产上线文档

## 目标

本文档记录把当前 Marzban sing-box POC 推到公网生产环境需要完成的工作、推荐部署形态、发布步骤、验证方法和回滚方案。

当前 POC 已在 Ubuntu 22.04 容器内验证：

- sing-box `1.13.14` 可作为核心进程启动、检查配置、重启和停止。
- 公共入口协议覆盖 `hysteria2`、`tuic`、`anytls`、`vmess`、`vless`、`trojan`、`shadowsocks`。
- 节点间链路使用 Hysteria2。
- 一跳任意入、任意出可工作：用户连接任意入口节点，入口节点按用户出口策略转发到指定出口节点。
- 10 节点全互联配置可生成并通过 `sing-box check`。

当前代码已经在 POC 基础上补齐 M1 到 M4 的生产骨架：真实数据库表、正式 API、Dashboard 基础控制区、节点配置生成、local/SSH 下发、订阅接入、近似节点统计和最小 bootstrap 脚本。后续仍需要按真实公网节点做证书签发、节点注册安全、监控告警和运维硬化。

## 上线范围

生产上线分两种范围。

### 小流量手工试运行

适合熟人内测，目标是尽快上公网验证真实网络质量。

可接受：

- 节点和用户数量少于 10 个。
- 配置由控制面或脚本生成后手工下发。
- 用户增删、出口变更通过重生成配置和重启 sing-box 生效。
- 流量统计只做粗略记录，不作为严格计费依据。
- Dashboard 可以先不完整，只提供后台 API 或手工操作。

不适合：

- 大量用户频繁改配置。
- 严格在线计费。
- 节点自动扩缩容。
- 面向陌生用户开放注册和自助购买。

### 面板完整生产化

适合长期使用，需要把 sing-box 做成 Marzban 的正式 runtime。

必须完成：

- 数据库迁移。
- Dashboard 页面接入。
- 订阅路由接入。
- 节点配置下发和状态回报。
- 证书、密钥、端口、健康检查管理。
- 统计任务从 Xray API 迁移到 sing-box 可用方案或近似方案。
- 发布、回滚和审计链路。

## 推荐架构

### 控制面

控制面继续使用 Marzban 的 FastAPI、数据库和管理员体系。

生产上新增或改造这些职责：

- 管理节点：公网访问地址、入口开关、出口开关、节点间链路端口、证书状态、配置 hash。
- 管理用户：协议凭据、允许协议、默认出口节点。
- 生成 sing-box 配置：按节点生成完整配置文件。
- 下发配置：把新配置下发到对应节点并执行 `sing-box check`。
- 应用配置：检查通过后重启或 reload 节点上的 sing-box。
- 生成订阅：按用户生成 sing-box/Mihomo 等客户端配置。

### 节点面

每个节点运行一个 sing-box 实例，既可以做入口，也可以做出口。

用户访问路径：

```text
client -> entry node public inbound -> selected exit outbound -> exit node node-link inbound -> internet
```

如果入口和出口是同一台节点：

```text
client -> entry node public inbound -> direct internet
```

生产初版不做多跳：

```text
client -> node-a -> node-b -> node-c -> internet
```

### 节点间链路

节点间链路统一用 Hysteria2。

原因：

- POC 已验证。
- 性能和穿透表现适合节点间转发。
- 内部链路协议统一后，配置、排障和轮换密钥更简单。

节点间 TLS 建议使用主控制面板维护的内部 CA：

- 控制面生成并保存内部 root CA 或 intermediate CA。
- 每个节点拿到自己的节点证书、节点私钥和内部 CA 证书。
- 入口节点连接出口节点时校验出口节点证书。
- 更严格时启用 mTLS，让出口节点也校验入口节点客户端证书。
- 内部 CA 只用于节点间链路，不用于面向用户的公网入口证书。

每个出口节点开放一个 `node-link-hysteria2` inbound。每个入口节点为其他出口节点生成一个 Hysteria2 outbound，例如：

```text
entry node-a outbound exit-node-b -> exit node-b inbound node-link-hysteria2
```

对于 10 个节点，全互联有 `10 * 9 = 90` 条有向链路。这个规模仍可接受。

## 镜像和运行基底

POC 镜像位于 `docker/singbox-poc/Dockerfile`，当前做法是：

```dockerfile
FROM ghcr.io/sagernet/sing-box:v1.13.14 AS singbox
FROM ubuntu:22.04
COPY --from=singbox /usr/local/bin/sing-box /usr/local/bin/sing-box
```

生产建议仍使用 Ubuntu 22.04 作为节点服务端基底，原因是调试成本低、包管理稳定、和 POC 环境一致。

生产节点镜像建议包含：

- `sing-box`
- `ca-certificates`
- `curl`
- `jq`
- `openssl`
- `iproute2`
- `dnsutils`
- `tcpdump`，只在 debug 镜像保留

生产镜像不要使用 `latest`，必须固定 sing-box 版本。升级版本时先在测试节点执行：

```bash
sing-box check -c /etc/sing-box/config.json
sing-box version
```

再跑 Docker POC：

```bash
./docker/singbox-poc/scripts/run-tests.sh
```

## 端口规划

当前 POC 默认端口：

| 用途 | 协议 | 默认端口 | 传输 |
|---|---|---:|---|
| 用户入口 | Hysteria2 | `11001` | UDP |
| 用户入口 | TUIC | `11002` | UDP |
| 用户入口 | AnyTLS | `11003` | TCP |
| 用户入口 | VMess | `11004` | TCP |
| 用户入口 | VLESS | `11005` | TCP |
| 用户入口 | Trojan | `11006` | TCP |
| 用户入口 | Shadowsocks | `11007` | TCP/UDP 按实际配置开放 |
| 节点间链路 | Hysteria2 | `12443` | UDP |

生产可以继续使用这组端口，也可以按节点改成更隐蔽的端口。无论选择哪种，都必须保证：

- 控制面记录每个节点的实际端口。
- 订阅生成使用真实端口。
- 防火墙同时放行 TCP/UDP 中对应的传输。
- 云厂商安全组和系统防火墙配置一致。

Ubuntu `ufw` 示例：

```bash
ufw allow 11001/udp
ufw allow 11002/udp
ufw allow 11003/tcp
ufw allow 11004/tcp
ufw allow 11005/tcp
ufw allow 11006/tcp
ufw allow 11007/tcp
ufw allow 11007/udp
ufw allow 12443/udp
ufw reload
```

## 地址和证书

节点间默认不要求域名。`public_host` 表示节点的公网访问地址，可以是域名，也可以直接是 IPv4/IPv6。

节点间链路推荐默认使用 IP-only：

```text
node-a public_host = 203.0.113.10
node-b public_host = 203.0.113.20
node-c public_host = 203.0.113.30
```

控制面内部 CA 给节点签发证书时，SAN 必须匹配节点之间实际连接使用的地址：

```text
IP:203.0.113.10
DNS:node-a
```

如果节点有域名，也可以使用域名：

```text
node-a.example.com -> 203.0.113.10
SAN = DNS:node-a.example.com,DNS:node-a
```

节点间链路要求：

- 使用控制面内部 CA 签发的节点证书。
- 入口节点连接出口节点时必须校验内部 CA。
- 节点间链路禁止设置 `insecure: true`。
- `server_name` 必须等于 `public_host`；如果 `public_host` 是 IP，证书 SAN 必须包含对应 IP。

用户入口允许两种无域名模式：

| 模式 | 配置 | 适用场景 |
|---|---|---|
| A. IP + 自建 CA | 节点 `public_tls_mode=ip-ca`，`public_tls_ca_cert_path` 指向客户端侧 CA 文件路径 | 熟人长期使用，安全性可接受 |
| C. IP + 跳过证书校验 | 节点 `public_tls_mode=ip-insecure` | 临时灰度、排障、非常小范围熟人使用 |

不做 B 模式，也就是不把证书指纹 pinning 作为默认交付路径。原因是客户端支持差异更大，维护成本高于收益。

有域名时仍可使用传统模式：

```text
用户入口：域名 + 公信证书
节点间链路：IP 或域名 + 控制面内部 CA
```

生产默认值：

```json
{"enabled": true, "server_name": "..."}
```

只有明确选择 C 模式时才允许输出：

```json
{"enabled": true, "server_name": "...", "insecure": true}
```

证书文件建议路径：

```text
/etc/sing-box/certs/fullchain.pem
/etc/sing-box/certs/privkey.pem
```

对应环境配置：

```env
SINGBOX_TLS_CERT_PATH=/etc/sing-box/certs/fullchain.pem
SINGBOX_TLS_KEY_PATH=/etc/sing-box/certs/privkey.pem
```

## 控制面内部 CA

节点间链路建议由主控制面板节点维护一个内部 CA。

参考 sing-box TLS 配置文档：

- https://sing-box.sagernet.org/configuration/shared/tls/

### CA 职责

控制面 CA 负责：

- 签发每个节点的 node-link 服务端证书。
- 可选签发每个节点的 node-link 客户端证书，用于 mTLS。
- 记录证书序列号、节点、签发时间、过期时间和吊销状态。
- 轮换即将过期的节点证书。

控制面 CA 不负责：

- 用户入口的公开 TLS 证书。
- 管理面板 HTTPS 证书。
- 客户端订阅里给用户使用的公信证书。

### 文件布局

控制面：

```text
/var/lib/marzban/ca/node-link/root-ca.crt
/var/lib/marzban/ca/node-link/root-ca.key
/var/lib/marzban/ca/node-link/issued/
```

节点：

```text
/etc/sing-box/node-link/ca.crt
/etc/sing-box/node-link/node.crt
/etc/sing-box/node-link/node.key
/etc/sing-box/node-link/client.crt      # 启用 mTLS 时需要
/etc/sing-box/node-link/client.key      # 启用 mTLS 时需要
```

权限要求：

```bash
chmod 700 /var/lib/marzban/ca/node-link
chmod 600 /var/lib/marzban/ca/node-link/root-ca.key
chmod 600 /etc/sing-box/node-link/node.key
chmod 600 /etc/sing-box/node-link/client.key
```

root CA 私钥只能保存在控制面，不能下发到任何节点。

### 证书命名

每个节点证书的 SAN 必须包含节点之间实际访问使用的地址。

示例：

```text
DNS:node-a.example.com
DNS:node-a
IP:203.0.113.10
```

节点间默认可以使用 IP 作为 `server_name`。如果使用 IP，证书必须包含 `IP:` SAN；如果使用域名，证书必须包含 `DNS:` SAN。

### 单向 TLS 配置

这是最低生产要求：入口节点校验出口节点的证书。

出口节点 `node-b` 的 node-link inbound：

```json
{
  "type": "hysteria2",
  "tag": "node-link-hysteria2",
  "listen": "::",
  "listen_port": 12443,
  "users": [
    {
      "name": "link-node-a",
      "password": "generated-link-secret"
    }
  ],
  "ignore_client_bandwidth": true,
  "tls": {
    "enabled": true,
    "certificate_path": "/etc/sing-box/node-link/node.crt",
    "key_path": "/etc/sing-box/node-link/node.key"
  }
}
```

入口节点 `node-a` 到 `node-b` 的 node-link outbound：

```json
{
  "type": "hysteria2",
  "tag": "exit-node-b",
  "server": "203.0.113.20",
  "server_port": 12443,
  "password": "generated-link-secret",
  "tls": {
    "enabled": true,
    "server_name": "203.0.113.20",
    "certificate_path": "/etc/sing-box/node-link/ca.crt"
  }
}
```

这里不能设置 `insecure: true`。

### mTLS 配置

更严格的生产模式建议启用 mTLS。这样出口节点除了校验 Hysteria2 用户密码，还会校验入口节点的客户端证书。

出口节点 `node-b` 的 node-link inbound 增加：

```json
{
  "tls": {
    "enabled": true,
    "certificate_path": "/etc/sing-box/node-link/node.crt",
    "key_path": "/etc/sing-box/node-link/node.key",
    "client_authentication": "require-and-verify",
    "client_certificate_path": [
      "/etc/sing-box/node-link/ca.crt"
    ]
  }
}
```

入口节点 `node-a` 到 `node-b` 的 node-link outbound 增加：

```json
{
  "tls": {
    "enabled": true,
    "server_name": "203.0.113.20",
    "certificate_path": "/etc/sing-box/node-link/ca.crt",
    "client_certificate_path": "/etc/sing-box/node-link/client.crt",
    "client_key_path": "/etc/sing-box/node-link/client.key"
  }
}
```

注意：

- `client_certificate_path` 和 `client_key_path` 是 sing-box `1.13.0` 后的字段，当前 POC 固定 `1.13.14` 可以覆盖。
- 上生产前需要在 Docker POC 中补一个 mTLS 用例，确认当前版本对 CA bundle 和客户端证书链的行为符合预期。
- 如果某个 sing-box 版本对 `client_certificate_path` 的 CA bundle 行为不符合预期，可以退回到 `client_certificate_public_key_sha256` 做客户端公钥 pinning。

### CA 轮换

CA 和节点证书轮换建议分开。

节点证书轮换：

1. 控制面签发新节点证书。
2. 下发新证书到节点 staging 路径。
3. 生成引用新证书的配置。
4. `sing-box check` 通过后滚动重启节点。
5. 确认链路恢复后删除旧证书。

CA 轮换：

1. 所有节点先下发新旧两个 CA。
2. 控制面开始签发新 CA 下的节点证书。
3. 滚动替换节点证书。
4. 所有节点都切到新 CA 后移除旧 CA。

CA 私钥泄露时，必须视为所有节点间链路信任失效，立即生成新 CA、重签节点证书、轮换所有节点间链路密码。

## 密钥和凭据

生产密钥不能使用 POC 里的固定字符串。

需要生成并保存：

- 用户通用 password，用于 Hysteria2、AnyTLS、Trojan 等。
- VMess UUID。
- VLESS UUID。
- TUIC UUID。
- Shadowsocks 2022 server password。
- Shadowsocks per-user password。
- 每条节点间链路的 Hysteria2 password。

节点间链路密钥是有向的：

```text
node-a -> node-b password != node-b -> node-a password
```

建议密钥轮换策略：

- 新增链路密钥时先让目标出口节点同时接受新旧密码。
- 所有入口节点切到新密码。
- 确认无旧密码连接后删除旧密码。

生产日志不得输出明文订阅、密码、UUID 和完整配置。

## 数据库改造

完整生产化至少需要这些字段或表。

### 节点

建议扩展节点表或新增 sing-box 节点表：

```text
singbox_nodes
  id
  name
  public_host
  entry_enabled
  exit_enabled
  node_link_port
  public_tls_mode
  public_tls_cert_path
  public_tls_key_path
  public_tls_ca_cert_path
  node_link_ca_cert_path
  node_link_cert_path
  node_link_key_path
  node_link_client_cert_path
  node_link_client_key_path
  node_link_cert_expires_at
  last_config_hash
  applied_config_hash
  last_seen_at
  status
```

如果证书文件路径由节点 agent 固定管理，数据库也可以只保存证书状态和过期时间，不保存绝对路径。

### 用户出口策略

初版直接在用户表增加：

```text
users.exit_node_id nullable
```

语义：

- `NULL`：入口节点本机直出。
- `exit_node_id == entry_node_id`：入口节点本机直出。
- `exit_node_id != entry_node_id`：入口节点转发到指定出口节点。

后续如果要做按入口节点细分，再升级为：

```text
user_route_policies
  id
  user_id
  entry_node_id nullable
  exit_node_id nullable
  priority
  enabled
```

### 节点链路

```text
node_links
  id
  from_node_id
  to_node_id
  protocol
  auth_name
  password_secret_ref
  mtls_enabled
  client_cert_secret_ref
  client_cert_expires_at
  enabled
  last_rotated_at
```

### 用户协议凭据

现有用户模型如果不能容纳多协议凭据，需要新增：

```text
user_singbox_credentials
  user_id
  password_secret_ref
  vmess_uuid
  vless_uuid
  tuic_uuid
  shadowsocks_password_secret_ref
  enabled_protocols
```

## 控制面环境变量

当前 POC 已支持一个最小 standalone 路径：

```env
CORE_RUNTIME=singbox
SINGBOX_EXECUTABLE_PATH=/usr/local/bin/sing-box
SINGBOX_STANDALONE_CONFIG_PATH=/etc/sing-box/config.json
```

当 `CORE_RUNTIME=singbox` 且设置 `SINGBOX_STANDALONE_CONFIG_PATH` 时，`python3 main.py` 会直接 exec：

```bash
/usr/local/bin/sing-box run -c /etc/sing-box/config.json
```

完整生产化建议补齐：

```env
CORE_RUNTIME=singbox
SINGBOX_EXECUTABLE_PATH=/usr/local/bin/sing-box
SINGBOX_CONFIG_DIR=/var/lib/marzban/singbox/configs
SINGBOX_WORK_DIR=/var/lib/sing-box
SINGBOX_TLS_CERT_PATH=/etc/sing-box/certs/fullchain.pem
SINGBOX_TLS_KEY_PATH=/etc/sing-box/certs/privkey.pem
SINGBOX_PUBLIC_TLS_CA_CERT_PATH=
SINGBOX_TLS_INSECURE=false
SINGBOX_NODE_LINK_PROTOCOL=hysteria2
SINGBOX_NODE_LINK_PORT=12443
SINGBOX_NODE_LINK_CA_CERT_PATH=/etc/sing-box/node-link/ca.crt
SINGBOX_NODE_LINK_CERT_PATH=/etc/sing-box/node-link/node.crt
SINGBOX_NODE_LINK_KEY_PATH=/etc/sing-box/node-link/node.key
SINGBOX_NODE_LINK_MTLS=true
SINGBOX_NODE_LINK_CLIENT_CERT_PATH=/etc/sing-box/node-link/client.crt
SINGBOX_NODE_LINK_CLIENT_KEY_PATH=/etc/sing-box/node-link/client.key
SINGBOX_RESTART_STRATEGY=checked-restart
RATE_LIMIT_ENABLED=true
RATE_LIMIT_TRUST_PROXY_HEADERS=false
API_RATE_LIMIT_REQUESTS=300
API_RATE_LIMIT_WINDOW_SECONDS=60
SUBSCRIPTION_RATE_LIMIT_REQUESTS=120
SUBSCRIPTION_RATE_LIMIT_WINDOW_SECONDS=60
LOGIN_RATE_LIMIT_REQUESTS=30
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
LOGIN_BACKOFF_ENABLED=true
LOGIN_BACKOFF_FREE_FAILURES=5
LOGIN_BACKOFF_BASE_SECONDS=2
LOGIN_BACKOFF_MAX_SECONDS=300
LOGIN_BACKOFF_RESET_SECONDS=900
```

用户入口 TLS 模式优先使用每个 `singbox_nodes.public_tls_mode` 控制。`SINGBOX_PUBLIC_TLS_CA_CERT_PATH` 和 `SINGBOX_TLS_INSECURE` 只作为旧配置或未设置节点字段时的兜底默认值。

`LOGIN_BACKOFF_*` 是登录失败指数退避配置。失败次数超过 `LOGIN_BACKOFF_FREE_FAILURES` 后返回 `429` 和 `Retry-After`，延迟按 `base * 2^n` 增长并受 `LOGIN_BACKOFF_MAX_SECONDS` 限制。

`RATE_LIMIT_TRUST_PROXY_HEADERS=true` 时会读取 `CF-Connecting-IP`、`X-Real-IP`、`X-Forwarded-For`。只有面板位于可信反代后面，且反代会覆盖这些 header 时才应该打开；直连公网时保持 `false`，避免客户端伪造来源 IP 绕过限速。

当前应用内限速是进程内内存实现，匹配当前 `workers=1` 的运行方式。多 worker、多容器或多面板实例时，必须改成 Redis/数据库共享计数，或者把限速完全放到 Nginx、Caddy、Cloudflare 等反代层。

## 配置生成和下发流程

生产发布每次配置变更都走同一条流水线。

1. 控制面读取数据库中的节点、用户、出口策略和链路密钥。
2. 为每个节点生成完整 sing-box JSON。
3. 对生成结果计算 `config_hash`。
4. 在控制面本地执行 `sing-box check -c generated-node.json`。
5. 把配置上传到目标节点的 staging 路径：

   ```text
   /etc/sing-box/config.json.next
   ```

6. 在目标节点执行：

   ```bash
   sing-box check -c /etc/sing-box/config.json.next
   ```

7. 检查通过后原子替换：

   ```bash
   mv /etc/sing-box/config.json /etc/sing-box/config.json.prev
   mv /etc/sing-box/config.json.next /etc/sing-box/config.json
   ```

8. 重启 sing-box：

   ```bash
   systemctl restart sing-box
   ```

9. 记录 `applied_config_hash`、发布时间、发布人和节点状态。
10. 运行健康检查和出口检查。

配置下发失败时不要覆盖当前运行配置。

## 节点部署方式

### systemd 方式

推荐生产初期使用 systemd，排障直接。

服务文件示例：

```ini
[Unit]
Description=sing-box service
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/sing-box run -c /etc/sing-box/config.json
ExecReload=/usr/local/bin/sing-box check -c /etc/sing-box/config.json
Restart=on-failure
RestartSec=5s
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
```

部署命令：

```bash
systemctl daemon-reload
systemctl enable sing-box
systemctl start sing-box
systemctl status sing-box
```

### Docker 方式

Docker 方式适合和现有容器化部署合并。

节点容器需要挂载：

```text
/etc/sing-box/config.json
/etc/sing-box/certs/
```

需要发布对应 TCP/UDP 端口。示例：

```yaml
services:
  sing-box:
    image: marzban-singbox-node:ubuntu2204
    restart: unless-stopped
    network_mode: host
    volumes:
      - /etc/sing-box/config.json:/etc/sing-box/config.json:ro
      - /etc/sing-box/certs:/etc/sing-box/certs:ro
    command: ["sing-box", "run", "-c", "/etc/sing-box/config.json"]
```

生产节点推荐使用 `network_mode: host`，避免 UDP 代理和端口映射引入额外问题。

## Bootstrap 安装脚本

原版 Marzban 的 README 引导用户使用外部 `Marzban-scripts` 仓库里的 `marzban.sh` 完成安装，例如：

```bash
sudo bash -c "$(curl -sL https://github.com/Gozargah/Marzban-scripts/raw/master/marzban.sh)" @ install
```

当前 sing-box POC 还没有实现对应的生产 bootstrap 脚本。上公网前需要补一个一键脚本，避免手工安装 Docker、systemd、证书目录、端口和配置文件时出错。

建议先在本仓库新增：

```text
scripts/singbox-bootstrap.sh
```

后续稳定后再考虑同步到独立脚本仓库，或 fork 原版 `Marzban-scripts` 增加 sing-box 分支。

### 子命令

脚本至少支持：

```bash
scripts/singbox-bootstrap.sh install
scripts/singbox-bootstrap.sh install-node
scripts/singbox-bootstrap.sh install-panel
scripts/singbox-bootstrap.sh update
scripts/singbox-bootstrap.sh restart
scripts/singbox-bootstrap.sh status
scripts/singbox-bootstrap.sh logs
scripts/singbox-bootstrap.sh check
scripts/singbox-bootstrap.sh uninstall
```

建议语义：

- `install`：单机安装控制面和本机 sing-box 节点。
- `install-panel`：只安装控制面、数据库、内部 CA 和管理面板。
- `install-node`：只安装远端 sing-box 节点。
- `update`：更新镜像或二进制，并保留旧版本回滚。
- `restart`：重启控制面和 sing-box。
- `status`：显示服务状态、版本、配置 hash、端口监听。
- `logs`：显示控制面和 sing-box 日志。
- `check`：执行环境、端口、证书和 `sing-box check`。
- `uninstall`：停止服务并可选保留数据目录。

### install-panel 职责

控制面安装必须完成：

- 检查系统版本，生产默认支持 Ubuntu 22.04。
- 安装 Docker Compose 或 systemd 运行依赖。
- 创建 Marzban 数据目录。
- 写入 `.env`。
- 生成或导入控制面内部 CA。
- 创建 CA 私钥目录并设置权限。
- 初始化数据库。
- 启动 Marzban 控制面。
- 创建初始管理员或提示执行管理员创建命令。
- 输出面板 URL、数据目录、CA 目录和下一步节点安装命令。

控制面数据目录建议：

```text
/var/lib/marzban
/var/lib/marzban/ca/node-link
/var/lib/marzban/singbox/configs
```

### install-node 职责

节点安装必须完成：

- 检查系统版本，生产默认支持 Ubuntu 22.04。
- 安装或更新固定版本 sing-box。
- 创建 `/etc/sing-box` 和 `/var/lib/sing-box`。
- 写入 systemd service 或 Docker Compose 文件。
- 创建 node-link 证书目录。
- 接收控制面下发的 `ca.crt`、`node.crt`、`node.key`。
- 启用 mTLS 时接收 `client.crt`、`client.key`。
- 写入初始 `/etc/sing-box/config.json`。
- 执行 `sing-box check -c /etc/sing-box/config.json`。
- 开放用户入口端口和节点间链路端口。
- 启动服务并验证端口监听。

节点目录建议：

```text
/etc/sing-box/config.json
/etc/sing-box/config.json.prev
/etc/sing-box/node-link/ca.crt
/etc/sing-box/node-link/node.crt
/etc/sing-box/node-link/node.key
/var/lib/sing-box
```

### 参数

脚本需要支持非交互参数，便于复制到远端节点执行：

```bash
scripts/singbox-bootstrap.sh install-node \
  --node-name node-a \
  --panel-url https://panel.example.com \
  --node-host 203.0.113.10 \
  --sing-box-version 1.13.14 \
  --node-link-port 12443 \
  --runtime systemd
```

最少参数：

- `--node-name`
- `--panel-url`
- `--node-host`
- `--sing-box-version`
- `--node-link-port`
- `--runtime systemd|docker`

敏感材料不要通过 shell 参数传递。证书、token、私钥应通过临时文件、stdin 或节点注册 API 获取。

### 幂等和回滚

bootstrap 脚本必须幂等：

- 目录已存在时不报错。
- 服务已存在时执行更新而不是重复创建。
- 配置变更前保留 `.prev`。
- 新配置必须先 `sing-box check`。
- 检查失败不能覆盖运行中的配置。
- 更新 sing-box 版本前保留旧二进制或旧镜像 tag。

失败回滚要求：

```bash
cp /etc/sing-box/config.json.prev /etc/sing-box/config.json
systemctl restart sing-box
```

如果是 Docker 运行，回滚到上一个镜像 tag，并重新启动容器。

### 安全要求

bootstrap 脚本不能：

- 把控制面 CA 私钥下发到节点。
- 在日志中输出订阅 token、节点注册 token、用户密码、UUID、私钥。
- 默认开启 `tls.insecure`。
- 默认开放无关端口。
- 在未确认数据目录的情况下删除 `/var/lib/marzban` 或 `/etc/sing-box`。

脚本应当：

- 默认使用 HTTPS 面板地址。
- 检查节点证书是否由控制面内部 CA 签发。
- 检查 node-link 证书 SAN 是否匹配 `--node-host`，IP 地址必须使用 `IP:` SAN。
- 检查防火墙和云安全组提示项。
- 输出明确的下一步验证命令。

### check 输出

`check` 子命令至少输出：

```text
OS: Ubuntu 22.04
sing-box: 1.13.14
runtime: systemd
config: ok
node-link ca: ok
node-link cert: ok, expires at ...
public cert: ok, expires at ...
ports: 11001/udp ok, 11002/udp ok, 11003/tcp ok, 12443/udp ok
service: active
config hash: ...
```

## 订阅

生产订阅需要接入 Marzban 现有订阅路由，而不是只使用 POC API。

需要支持：

- sing-box JSON 订阅。
- Mihomo/Clash YAML 订阅。
- 用户可用协议列表。
- 用户可用入口节点列表。
- 用户默认出口策略。
- TLS `server_name` 和证书校验配置。

`app/core/singbox/subscription.py` 已接入正式 `/sub/{token}` 路由，支持 sing-box JSON 和 Clash/Mihomo YAML，并可用 `entry_node_id` 选择入口节点。生产前仍建议继续补齐各客户端兼容性细节，尤其是：

- Hysteria2 字段差异。
- TUIC 字段差异。
- AnyTLS 客户端支持情况。
- Shadowsocks 2022 密码格式。
- 老客户端对 VMess/VLESS/Trojan TCP 裸配置的兼容性。

## Dashboard 改造

当前已经有真实 Dashboard 基础接入：

```text
app/dashboard/src/components/SingBoxPanel.tsx
```

已覆盖：

- 节点列表和入口/出口开关。
- 节点公网访问地址、链路数量、状态和配置 hash。
- 节点级用户入口 TLS 模式：`system-ca`、`ip-ca`、`ip-insecure`。
- 配置 dry-run 检查。
- 重建节点链路。
- 增加节点。
- 按用户设置出口节点和可用协议。

后续可继续增强：

- 把 sing-box 出口节点选择嵌入原用户编辑页。
- 增加配置 diff、应用确认和回滚操作。
- 增加证书过期状态和 CA 轮换操作。

## 流量统计

POC 不做精确统计；当前生产骨架提供节点级近似统计表和上报 API。

熟人小流量试运行建议先采用粗略统计：

- 节点级网卡流量。
- sing-box 进程级日志和连接观察。
- 出口节点按用户 `auth_user` 做可用范围内的近似统计。

生产计费前必须确认：

- sing-box 当前版本可用的统计接口。
- 每个 inbound/outbound 和用户维度是否能稳定归因。
- 重启、断线、节点间转发是否会导致漏计或重复计。

在无法稳定按用户计量前，不要做严格后付费账单。

## 上线前检查清单

### 代码

- `git diff --check` 通过。
- Python 编译检查通过。
- `ruff` 通过。
- Docker POC 全量通过。
- 节点间配置生成器禁止输出 `insecure: true`。
- 用户入口只有显式选择 C 模式时才允许输出 `insecure: true`。
- 生产配置生成器不使用 POC 固定密码和 UUID。
- 节点间内部 CA 配置已生成并通过 `sing-box check`。
- mTLS 配置已在 Docker POC 或测试节点实测。

### 节点

- 每个节点公网访问地址正确；域名模式检查 DNS，IP-only 模式检查公网 IP 可达。
- 每个节点证书有效，SAN 匹配 `public_host`。
- 每个节点已安装控制面内部 CA 证书。
- 每个节点 node-link 证书未过期。
- 每个节点公网端口放行。
- 每个节点 `sing-box check` 通过。
- 每个节点系统时间同步。
- 每个节点 `nofile` 限制足够高。
- 每个节点磁盘日志轮转已配置。

### 控制面

- 数据库迁移已执行。
- 管理员能查看节点状态。
- 管理员能修改用户出口节点。
- 配置 hash 能正确记录。
- 下发失败不会覆盖旧配置。
- 发布动作有审计日志。

### 客户端

- sing-box 客户端订阅可用。
- Mihomo/Clash 订阅可用。
- 至少测试 Hysteria2、TUIC、AnyTLS、Trojan。
- 老协议 VMess/VLESS/Shadowsocks 按实际客户端验证。

## 上线步骤

### 1. 准备节点

每台节点：

```bash
apt-get update
apt-get install -y ca-certificates curl jq openssl iproute2 dnsutils
install -m 0755 sing-box /usr/local/bin/sing-box
mkdir -p /etc/sing-box/certs
mkdir -p /var/lib/sing-box
```

检查版本：

```bash
sing-box version
```

### 2. 准备公网地址、用户入口证书和内部 CA

确保：

```bash
curl -4 https://ifconfig.me
openssl x509 -in /etc/sing-box/certs/fullchain.pem -noout -subject -dates
```

如果使用域名模式，再检查 DNS：

```bash
dig +short node-a.example.com
```

控制面生成或加载内部 CA：

```bash
mkdir -p /var/lib/marzban/ca/node-link
chmod 700 /var/lib/marzban/ca/node-link
openssl genrsa -out /var/lib/marzban/ca/node-link/root-ca.key 4096
openssl req -x509 -new -nodes \
  -key /var/lib/marzban/ca/node-link/root-ca.key \
  -sha256 -days 3650 \
  -out /var/lib/marzban/ca/node-link/root-ca.crt \
  -subj "/CN=Marzban Node Link CA"
chmod 600 /var/lib/marzban/ca/node-link/root-ca.key
```

为每个节点签发 node-link 证书，并把这些文件下发到节点：

```text
/etc/sing-box/node-link/ca.crt
/etc/sing-box/node-link/node.crt
/etc/sing-box/node-link/node.key
```

启用 mTLS 时还要下发：

```text
/etc/sing-box/node-link/client.crt
/etc/sing-box/node-link/client.key
```

### 3. 生成初始配置

控制面生成每个节点的配置：

```text
node-a.config.json
node-b.config.json
node-c.config.json
```

每个配置先本地检查：

```bash
sing-box check -c node-a.config.json
```

### 4. 下发配置

上传到节点：

```bash
scp node-a.config.json root@node-a.example.com:/etc/sing-box/config.json.next
```

IP-only 节点直接用公网 IP：

```bash
scp node-a.config.json root@203.0.113.10:/etc/sing-box/config.json.next
```

节点上检查：

```bash
sing-box check -c /etc/sing-box/config.json.next
```

### 5. 启动服务

```bash
mv /etc/sing-box/config.json.next /etc/sing-box/config.json
systemctl restart sing-box
systemctl status sing-box
```

### 6. 验证入口和出口

至少验证这些路径：

```text
client -> node-a Hysteria2 -> node-a direct
client -> node-a Hysteria2 -> node-b exit
client -> node-b TUIC -> node-c exit
client -> node-c AnyTLS -> node-a exit
client -> node-a Trojan -> node-b exit
```

验证出口 IP：

```bash
curl --proxy socks5h://127.0.0.1:2080 https://ifconfig.me
```

实际看到的 IP 必须等于配置的出口节点公网 IP。

### 7. 小流量灰度

先只放 1 到 3 个熟人用户。

灰度观察：

- 连接成功率。
- 延迟和丢包。
- UDP 协议稳定性。
- 节点 CPU、内存、带宽。
- sing-box 日志是否有认证失败、TLS 错误、链路失败。
- 用户出口是否符合策略。

灰度至少观察 24 小时，再扩大用户。

## 配置变更流程

### 增加用户

1. 生成用户密码和 UUID。
2. 写入数据库。
3. 重生成所有入口节点配置。
4. 对所有受影响节点执行 `sing-box check`。
5. 滚动重启入口节点。
6. 生成订阅并实测连接。

### 修改用户出口

1. 修改 `users.exit_node_id`。
2. 重生成该用户可能进入的入口节点配置。
3. 检查配置。
4. 滚动重启入口节点。
5. 验证出口 IP。

### 增加节点

1. 创建节点记录。
2. 配置公网访问地址、用户入口证书、内部 CA 节点证书和防火墙。
3. 为新节点生成到所有旧节点的链路。
4. 为所有旧节点生成到新节点的链路。
5. 先部署新节点。
6. 再滚动更新旧节点。
7. 验证新节点入、新节点出、旧节点到新节点出。

### 删除节点

1. 先禁止该节点作为入口。
2. 把用户出口迁移到其他节点。
3. 重生成并下发所有受影响配置。
4. 确认无流量后禁止该节点作为出口。
5. 删除节点间链路。
6. 停止节点服务。

## 健康检查

每个节点至少有两类检查。

### 本机检查

```bash
systemctl is-active sing-box
sing-box check -c /etc/sing-box/config.json
journalctl -u sing-box -n 100 --no-pager
```

### 路径检查

从测试客户端按订阅连入指定入口，访问出口探测地址：

```bash
curl --proxy socks5h://127.0.0.1:2080 https://ifconfig.me
```

控制面保存期望出口 IP，检查实际出口是否匹配。

## 监控和告警

生产至少监控：

- sing-box 进程存活。
- 节点 CPU、内存、磁盘。
- 网卡入站、出站带宽。
- UDP 丢包或异常错误日志。
- 认证失败次数。
- TLS 握手失败次数。
- 节点间链路失败次数。
- 配置 hash 是否和控制面期望一致。

告警优先级：

- P0：节点进程停止、核心端口不可达。
- P1：节点间链路不可达、出口 IP 不匹配。
- P2：认证失败暴增、TLS 错误暴增、带宽接近上限。

## 回滚

每次发布前保留：

```text
/etc/sing-box/config.json.prev
/etc/sing-box/config.json
```

配置发布失败或健康检查失败时：

```bash
cp /etc/sing-box/config.json.prev /etc/sing-box/config.json
sing-box check -c /etc/sing-box/config.json
systemctl restart sing-box
```

控制面要把节点状态标记为：

```text
rollback_applied
```

并记录失败配置 hash。

如果 sing-box 版本升级失败，回滚镜像或二进制版本，再使用旧配置启动。

## 安全要求

生产前必须完成：

- 禁止在配置、日志、API 响应中泄露密码、UUID、订阅内容。
- 管理 API 只允许 sudo admin 操作节点配置和链路密钥。
- 订阅 token 必须足够随机，支持重置。
- 节点下发通道必须有认证和加密。
- 节点间链路不使用 `insecure: true`。
- 节点间链路至少校验控制面内部 CA，推荐启用 mTLS。
- 控制面 CA 私钥不能下发到节点。
- 防火墙只开放必要端口。
- SSH 只允许密钥登录。
- 管理面板开启 HTTPS。
- 管理 API 和订阅 API 开启限速。
- 登录失败启用指数退避，并返回 `Retry-After`。
- 登录失败通知不要包含用户输入的明文密码。

## 实现状态

M1 到 M4 的代码骨架已经落地：

- 真实数据库迁移：`singbox_nodes`、`singbox_node_links`、`singbox_user_credentials`、`singbox_route_policies`、`singbox_node_usages`。
- Dashboard 基础接入：`SingBoxPanel`，支持节点级入口 TLS 模式控制。
- 正式 API：`/api/singbox/...`。
- 节点配置生成和 hash 记录。
- local/SSH/manual 三种配置部署模式，以及按节点顺序滚动 deploy API。
- 控制面内部 CA 初始化和节点证书签发 API。
- 生产 TLS 默认安全，节点间 mTLS 由 Docker POC 验证。
- 订阅路由接入现有 `/sub/{token}`。
- 粗略节点统计上报和查询。
- 最小 `scripts/singbox-bootstrap.sh`，支持 `install-node`、`check`、`restart`、`logs`。

仍需生产硬化：

- 控制面 CA 轮换、吊销和节点注册安全流程。
- 节点注册 token 和下发通道鉴权。
- 发布审计、配置 diff、人工确认和一键回滚 UI。
- 更完整的客户端订阅兼容性测试。
- 真实公网监控告警和日志脱敏策略。

## 建议里程碑

### M1：手工公网试运行

目标：3 台公网节点，1 到 3 个熟人用户。

交付：

- 生产证书。
- 手工生成节点配置。
- systemd 或 Docker 运行 sing-box。
- 最小 bootstrap 脚本，至少支持 `install-node`、`check`、`restart`、`logs`。
- 手工订阅文件。
- 出口 IP 验证。
- 回滚脚本。

预计：3 到 7 天。

### M2：面板可控

目标：管理员能在面板改用户出口和节点状态。

交付：

- DB migration。
- Dashboard 基础页面。
- 正式 API。
- 配置生成和 hash 记录。

预计：1 到 2 周。

### M3：自动下发

目标：节点配置自动下发、检查、应用、回滚。

交付：

- 节点 agent 或 SSH 下发器。
- 远端 `sing-box check`。
- 滚动重启。
- 健康检查。

预计：1 周。

### M4：订阅和统计

目标：用户能直接使用现有订阅入口，管理员能看到粗略用量。

交付：

- sing-box/Mihomo 订阅。
- 用户协议选择。
- 入口节点选择。
- 近似流量统计。

预计：1 周。

## 最小生产准入标准

可以上小流量公网前，至少满足：

- 节点间 `public_host` 可达，node-link 证书 SAN 匹配 IP 或域名。
- 用户入口选择 A 模式时客户端已拿到自建 CA，选择 C 模式时已明确接受 `insecure=true` 风险。
- 所有生产配置 `sing-box check` 通过。
- 节点间使用控制面内部 CA，TLS 校验开启。
- POC 固定密码全部替换。
- 管理 API、订阅 API 和登录失败退避限速已开启。
- 至少 Hysteria2、TUIC、AnyTLS、Trojan 实测通过。
- 任意入、任意出至少覆盖 3 条真实路径。
- 有明确回滚文件和回滚命令。
- 管理员知道当前不是严格计费版本。

未满足这些条件前，不建议开放给非熟人用户。
