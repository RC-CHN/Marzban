# sing-box POC 改造设计

## 背景

当前 Marzban 的核心运行时围绕 Xray 设计：

- `app/xray/core.py` 负责本机 Xray 进程生命周期。
- `app/xray/config.py` 负责解析 Xray 配置、注入 API inbound、把数据库用户写进 inbound clients。
- `xray_api/` 负责通过 Xray gRPC API 增删用户和读取统计。
- `app/jobs/record_usages.py` 依赖 Xray stats 记录用户流量。

目标是把运行时替换为 sing-box，同时保留现有用户管理面板、订阅、节点概念和粗略流量统计能力。

官方参考：

- sing-box Docker: https://sing-box.sagernet.org/installation/docker/
- sing-box inbound/outbound 列表: https://sing-box.sagernet.org/configuration/inbound/ 和 https://sing-box.sagernet.org/configuration/outbound/
- route rule/action: https://sing-box.sagernet.org/configuration/route/rule/ 和 https://sing-box.sagernet.org/configuration/route/rule_action/
- dial `detour`: https://sing-box.sagernet.org/configuration/shared/dial/
- Hysteria2: https://sing-box.sagernet.org/configuration/inbound/hysteria2/
- TUIC: https://sing-box.sagernet.org/configuration/inbound/tuic/
- AnyTLS: https://sing-box.sagernet.org/configuration/inbound/anytls/
- VMess/VLESS/Trojan/Shadowsocks: https://sing-box.sagernet.org/configuration/inbound/vmess/、https://sing-box.sagernet.org/configuration/inbound/vless/、https://sing-box.sagernet.org/configuration/inbound/trojan/、https://sing-box.sagernet.org/configuration/inbound/shadowsocks/

## POC 目标

必须验证：

1. sing-box 可以替代 Xray 作为核心进程启动、停止、重启和读取日志。
2. 支持现有 Xray 协议类型：`vmess`、`vless`、`trojan`、`shadowsocks`。
3. 新增支持：`hysteria2`、`tuic`、`anytls`。
4. 支持最多十来个节点的一跳任意入、任意出：
   - 用户连接任意入口节点。
   - 控制面按用户出口策略把流量转发到指定出口节点。
   - 不做多跳路径。
5. 用 Docker 本地多容器验证节点互联和出口行为。
6. 只做粗略流量统计，不做精确计费。

POC 不做：

- 多跳链路，例如 A -> B -> C -> Internet。
- 动态热更新用户。POC 使用完整配置重生成 + 重启 sing-box。
- 精确账单、分摊出口成本、链路成本结算。
- 完整 Xray 配置无损迁移。
- ShadowTLS、Naive、Snell、WireGuard、Tor、SSH 等额外协议。
- 生产级 UI 美化。

## 版本策略

初始版本建议固定 sing-box Docker 镜像，不使用 `latest`。

推荐从当前稳定线开始：

```text
ghcr.io/sagernet/sing-box:v1.13.14
```

注意：

- AnyTLS 文档标注从 sing-box `1.12.0` 起可用。
- Snell inbound 文档标注从 `1.14.0` 起，不纳入本 POC。
- sing-box 新的 `service/api` 文档标注从 `1.14.0` 起，不作为 POC 依赖。
- V2Ray API 文档写明不是默认包含能力，POC 不能强依赖它做计费。

## 总体架构

保留 FastAPI 控制面和数据库，替换核心运行时层。

建议新增抽象：

```text
app/core/
  __init__.py
  runtime.py           # Runtime 抽象接口
  singbox/
    __init__.py
    core.py            # sing-box 进程生命周期
    config.py          # sing-box 配置生成和解析
    operations.py      # 用户/节点变更后的重载动作
    node.py            # 后续远端节点控制适配
```

当前实现已经切换为 sing-box only，不再保留 `app/xray/`、`xray_api/`
和旧运行时配置。生产和测试统一使用项目自带的 sing-box
二进制；`CORE_RUNTIME` 固定为 `singbox`，只保留 sing-box 相关路径：

```env
SINGBOX_EXECUTABLE_PATH=/usr/local/bin/sing-box
SINGBOX_CONFIG_PATH=/var/lib/marzban/singbox/config.json
SINGBOX_WORK_DIR=/var/lib/sing-box
```

控制面只依赖 Runtime 抽象：

```python
class CoreRuntime:
    def start(self, config): ...
    def stop(self): ...
    def restart(self, config): ...
    def started(self) -> bool: ...
    def get_logs(self): ...
    def get_version(self) -> str: ...
    def build_config_for_node(self, node_id: int): ...
```

POC 可以只实现本机多配置生成和 Docker lab，远端节点控制后置。

## 一跳任意入任意出模型

节点既可以做入口，也可以做出口。

假设有 `node-a`、`node-b`、`node-c`、`node-d`。

用户连接 `node-a` 的公共 inbound，出口策略指定 `node-c`，流量路径：

```text
client -> node-a public inbound -> node-a outbound(exit-node-c) -> node-c node-link inbound -> direct internet
```

如果用户出口就是当前入口节点：

```text
client -> node-a public inbound -> direct internet
```

不允许：

```text
client -> node-a -> node-b -> node-c -> internet
```

## 节点间内部链路

节点间链路建议统一使用 Hysteria2：

- 性能好。
- 配置简单。
- 作为内部链路不直接暴露给用户订阅。
- 每个目标节点只需要一个 `node-link-hysteria2` inbound，里面放所有来源节点的用户。

目标节点 `node-b` 的内部 inbound：

```json
{
  "type": "hysteria2",
  "tag": "node-link-hy2",
  "listen": "::",
  "listen_port": 2443,
  "users": [
    {
      "name": "link-node-a",
      "password": "generated-secret-a-to-b"
    },
    {
      "name": "link-node-c",
      "password": "generated-secret-c-to-b"
    }
  ],
  "ignore_client_bandwidth": true,
  "tls": {
    "enabled": true,
    "certificate_path": "/etc/sing-box/certs/cert.pem",
    "key_path": "/etc/sing-box/certs/key.pem"
  }
}
```

来源节点 `node-a` 到 `node-b` 的 outbound：

```json
{
  "type": "hysteria2",
  "tag": "exit-node-b",
  "server": "203.0.113.20",
  "server_port": 2443,
  "password": "generated-secret-a-to-b",
  "tls": {
    "enabled": true,
    "server_name": "203.0.113.20",
    "insecure": false
  }
}
```

Docker POC 使用自签证书，允许：

```json
"tls": {
  "enabled": true,
  "insecure": true
}
```

生产环境节点间必须改为控制面内部 CA，并允许默认使用 IP SAN。

## 用户出口策略

POC 使用全局用户出口策略，不区分入口节点。

新增字段：

```text
users.exit_node_id nullable
```

语义：

- `NULL`：入口节点本机直出。
- `exit_node_id == current_node_id`：本机直出。
- `exit_node_id != current_node_id`：入口节点转发到目标出口节点。

后续如果需要按入口节点细分，再升级为表：

```text
user_route_policies
  id
  user_id
  entry_node_id nullable
  exit_node_id nullable
  priority
  enabled
```

POC 先不做这张表。

## 数据模型改造

### 协议枚举

扩展 `ProxyTypes`：

```python
class ProxyTypes(str, Enum):
    VMess = "vmess"
    VLESS = "vless"
    Trojan = "trojan"
    Shadowsocks = "shadowsocks"
    Hysteria2 = "hysteria2"
    TUIC = "tuic"
    AnyTLS = "anytls"
```

### 用户协议凭据

统一生成 `auth_name`，用于 sing-box `users[].name` 和 route rule 的 `auth_user` 匹配。

建议格式：

```text
u{user.id}
```

理由：

- 稳定。
- 不受用户名字符集影响。
- 不怕用户名重命名，虽然当前用户名通常不改。

订阅展示仍用用户可读的 `username`。

各协议用户字段：

| 协议 | sing-box 用户字段 | Marzban 存储 |
|---|---|---|
| VMess | `name`, `uuid`, `alterId` | `id`, `alterId=0` |
| VLESS | `name`, `uuid`, `flow` | `id`, `flow` |
| Trojan | `name`, `password` | `password` |
| Shadowsocks | top-level `method/password`, `users[].name/password` | `method`, `password` |
| Hysteria2 | `name`, `password` | `password` |
| TUIC | `name`, `uuid`, `password` | `uuid`, `password` |
| AnyTLS | `name`, `password` | `password` |

Shadowsocks 特别注意：

- sing-box multi-user 推荐 2022 methods 时需要 top-level server password。
- 当前 Marzban 用户模型允许用户带 method。
- POC 为降低复杂度，先限制一个 Shadowsocks inbound 使用同一个 method。
- 如果要支持用户不同 method，需要按 method 拆分 inbound 或拒绝混用。

### 节点表扩展

在 `nodes` 上增加：

```text
public_host            string nullable
entry_enabled          bool default true
exit_enabled           bool default true
node_link_port         int nullable
node_link_protocol     string default "hysteria2"
last_config_hash       string nullable
last_config_at         datetime nullable
```

`public_host` 用于其他节点连接此节点，可以是公网 IP 或域名。Docker POC 中可以用 service name，例如 `node-b`。

### 节点链路表

新增 directed link 表：

```text
node_links
  id
  from_node_id
  to_node_id
  protocol              default "hysteria2"
  auth_name             e.g. "link-node-a"
  password              generated
  enabled               bool
  created_at
  updated_at
```

十个节点全互通时最多：

```text
10 * 9 = 90 directed links
```

这个规模完全可接受。

## sing-box 配置生成

每个节点生成一份完整配置。

输入：

- 当前节点。
- 所有 active/on_hold 用户。
- 当前节点启用的公共 inbound。
- 所有节点。
- `node_links`。
- 每个用户的 `exit_node_id`。

输出：

```json
{
  "log": {},
  "dns": {},
  "inbounds": [],
  "outbounds": [],
  "route": {
    "rules": [],
    "final": "direct"
  },
  "experimental": {}
}
```

### 公共 inbound

每个节点按启用协议生成公共 inbound。

Hysteria2 示例：

```json
{
  "type": "hysteria2",
  "tag": "public-hy2",
  "listen": "::",
  "listen_port": 443,
  "users": [
    {
      "name": "u1",
      "password": "user-hy2-password"
    }
  ],
  "ignore_client_bandwidth": true,
  "tls": {
    "enabled": true,
    "certificate_path": "/etc/sing-box/certs/cert.pem",
    "key_path": "/etc/sing-box/certs/key.pem"
  }
}
```

TUIC 示例：

```json
{
  "type": "tuic",
  "tag": "public-tuic",
  "listen": "::",
  "listen_port": 5443,
  "users": [
    {
      "name": "u1",
      "uuid": "059032a9-7d40-4a96-9bb1-36823d848068",
      "password": "user-tuic-password"
    }
  ],
  "congestion_control": "bbr",
  "zero_rtt_handshake": false,
  "tls": {
    "enabled": true,
    "certificate_path": "/etc/sing-box/certs/cert.pem",
    "key_path": "/etc/sing-box/certs/key.pem"
  }
}
```

AnyTLS 示例：

```json
{
  "type": "anytls",
  "tag": "public-anytls",
  "listen": "::",
  "listen_port": 7443,
  "users": [
    {
      "name": "u1",
      "password": "user-anytls-password"
    }
  ],
  "tls": {
    "enabled": true,
    "certificate_path": "/etc/sing-box/certs/cert.pem",
    "key_path": "/etc/sing-box/certs/key.pem"
  }
}
```

VMess/VLESS/Trojan/Shadowsocks 按 sing-box inbound 文档生成。POC 优先验证基础 TCP/TLS 和 WS/gRPC 中至少一个 transport，完整迁移当前 Xray 所有 transport 组合作为第二阶段。

### 内部 node-link inbound

当前节点作为出口节点时，生成 `node-link-hy2` inbound。

只加入启用的来源节点链路用户：

```json
"users": [
  {
    "name": "link-node-a",
    "password": "secret-a-to-current"
  }
]
```

### 出口 outbounds

每个节点至少有：

```json
{ "type": "direct", "tag": "direct" }
{ "type": "block", "tag": "block" }
```

如果当前节点是 `node-a`，并且存在 `node-a -> node-b` 链路，则生成：

```json
{
  "type": "hysteria2",
  "tag": "exit-node-b",
  "server": "203.0.113.20",
  "server_port": 2443,
  "password": "secret-a-to-b",
  "tls": {
    "enabled": true,
    "server_name": "203.0.113.20"
  }
}
```

### 用户路由规则

如果用户 `u1` 的出口是 `node-b`，当前生成的是 `node-a` 的配置：

```json
{
  "inbound": ["public-hy2", "public-tuic", "public-anytls", "public-vless", "public-vmess", "public-trojan", "public-ss"],
  "auth_user": "u1",
  "action": "route",
  "outbound": "exit-node-b"
}
```

如果用户出口为空或出口就是当前节点，不生成用户专属规则，走 `final: direct`。

规则排序：

1. 用户出口规则。
2. 私网/保留地址 block 或 direct 规则，按现有策略决定。
3. 默认 `final: direct`。

POC 不做 selector 动态切换。selector 只能通过 Clash API 控制，后续如果要“用户在线切出口”再引入。

## Runtime 行为

POC 不使用 sing-box 动态 API 增删用户。

用户创建、修改、删除、出口节点变化时：

1. 更新数据库。
2. 重新生成受影响节点的配置。
3. 写入配置文件。
4. 重启这些节点的 sing-box。

受影响节点：

- 用户入口可能出现的所有 entry 节点。
- 用户新旧出口节点不一定需要重启，除非 node-link inbound 用户变化。
- 节点链路变化时，重启 from/to 两侧节点。

对于十来个节点、熟人使用，这个策略足够简单可靠。

## 订阅生成

当前 `app/subscription/singbox.py` 已经存在 sing-box 客户端配置生成器，但只覆盖现有协议。需要扩展：

- Hysteria2 outbound。
- TUIC outbound。
- AnyTLS outbound。

客户端订阅只包含用户连接入口节点的信息，不暴露节点间内部链路。

用户看到的是：

```text
client -> selected entry node
```

出口节点由服务端 route 决定，订阅里不体现。

对于同一用户多入口节点：

- 每个入口节点生成一个 outbound。
- remark 中包含入口节点名和协议。
- 用户不需要知道最终出口。

## API 设计

POC 最少新增/修改：

```text
GET  /api/nodes
PUT  /api/user/{username}/exit-node
POST /api/singbox/config/rebuild
GET  /api/singbox/config/{node_id}
POST /api/singbox/restart/{node_id}
GET  /api/singbox/links
POST /api/singbox/links/rebuild
```

`PUT /api/user/{username}/exit-node`：

```json
{
  "exit_node_id": 2
}
```

设置为 `null` 表示本机直出。

`POST /api/singbox/links/rebuild`：

- 为所有 enabled nodes 生成缺失的 directed links。
- 不覆盖已有密码，除非传 `rotate=true`。

## Dashboard POC

最小 UI：

1. 用户编辑弹窗增加 `Exit node` 下拉框：
   - `Direct on entry node`
   - `node-a`
   - `node-b`
   - ...
2. Nodes 页面显示：
   - entry enabled
   - exit enabled
   - node-link port
   - generated links count
3. Core config 页面暂时显示 sing-box JSON。

## Docker POC 实验室

允许使用本地 Docker 拉镜像验证。建议新增：

```text
 docker/singbox-poc/
  docker-compose.yml
  README.md
  Dockerfile
  scripts/
    generate.py
    run-tests.sh
    whoami.py
  certs/
  generated/
    node-a/config.json
    node-b/config.json
    node-c/config.json
    client-alice/config.json
```

### Compose 拓扑

服务：

- `node-a`: sing-box 节点。
- `node-b`: sing-box 节点。
- `node-c`: sing-box 节点。
- `client-alice`: sing-box 客户端容器，提供本地 mixed inbound。
- `whoami`: HTTP echo 服务，用于验证出口源地址。

网络：

```text
poc_net
  node-a
  node-b
  node-c
  client-alice
  whoami
```

`whoami` 返回请求来源 IP。验证出口时，期望看到出口节点容器 IP。

### node-a 配置目标

- 公共 Hysteria2 inbound: `public-hy2`
- 公共 TUIC inbound: `public-tuic`
- 公共 AnyTLS inbound: `public-anytls`
- 内部 node-link inbound: `node-link-hy2`
- 到 `node-b` 的 outbound: `exit-node-b`
- 到 `node-c` 的 outbound: `exit-node-c`
- 路由：
  - `auth_user=u1` -> `exit-node-b`
  - 其他 -> direct

### node-b 配置目标

- 内部 node-link inbound 接收 `link-node-a`
- 默认 direct 出口

### client-alice 配置目标

客户端容器跑 sing-box：

- inbound: mixed socks/http `127.0.0.1:2080`
- outbound: Hysteria2/TUIC/AnyTLS/VMess/VLESS/Trojan/Shadowsocks 任一协议连接 `node-a`

容器内执行：

```bash
curl -x socks5h://127.0.0.1:2080 http://whoami
```

如果 alice 被配置为 `exit_node=node-b`，`whoami` 应显示来源为 `node-b`。

### 验收用例

| 用例 | 入口 | 出口策略 | 预期 |
|---|---|---|---|
| HY2 direct | node-a hysteria2 | null | whoami 来源为 node-a |
| HY2 remote exit | node-a hysteria2 | node-b | whoami 来源为 node-b |
| TUIC remote exit | node-a tuic | node-c | whoami 来源为 node-c |
| AnyTLS remote exit | node-b anytls | node-a | whoami 来源为 node-a |
| VMess remote exit | node-a vmess | node-b | whoami 来源为 node-b |
| VLESS remote exit | node-a vless | node-b | whoami 来源为 node-b |
| Trojan remote exit | node-a trojan | node-b | whoami 来源为 node-b |
| Shadowsocks remote exit | node-a shadowsocks | node-b | whoami 来源为 node-b |

### Docker 执行草案

后续实施时使用：

```bash
./docker/singbox-poc/scripts/run-tests.sh
```

如果需要拉镜像或访问外部网络，需要在执行时申请网络权限。

## 粗略统计方案

POC 不追求精确计费。

优先级：

1. 能显示节点在线、进程是否启动。
2. 能粗略估算用户入口流量。
3. 能粗略显示节点出口总流量。

可选实现路径：

- 尝试启用 V2Ray API stats。如果当前 sing-box 镜像支持，则按 `auth_name` 统计用户。
- 如果 V2Ray API 不可用，POC 允许暂时不显示 per-user 实时用量。
- 节点总流量可先通过 Docker/系统网卡统计或 sing-box 日志采样估算。

计费规则：

- 只按入口节点看到的用户流量估算。
- 节点间链路流量和出口节点总流量只做运维参考。
- 不做双倍计费。

## 迁移策略

POC 不直接迁移生产数据。

正式迁移时：

1. 保留旧 Xray 字段和配置。
2. 为每个用户生成 sing-box 协议凭据：
   - VMess/VLESS 复用 UUID。
   - Trojan/Shadowsocks 复用 password。
   - Hysteria2/TUIC/AnyTLS 新增凭据。
3. 为每个用户设置默认 `exit_node_id = NULL`。
4. 先生成配置但不启用。
5. 通过 Docker lab 和单真实节点验证。
6. 再切换 `CORE_RUNTIME=singbox`。

## 风险和决策点

### 1. 用户统计能力

sing-box 的 per-user stats 不应在 POC 前被假定可用。要先验证当前 Docker 镜像是否包含可用统计接口。

决策：

- POC 阶段统计不是阻塞项。
- 后续如果需要稳定统计，可以考虑自建 sidecar 或日志采集。

### 2. Shadowsocks 多 method

现有 Marzban 用户可带 Shadowsocks method。sing-box multi-user inbound 更适合同一 inbound 固定 method。

决策：

- POC 限制每个 Shadowsocks inbound 一个 method。
- UI/API 对混用 method 做校验。

### 3. Xray transport 兼容

sing-box 支持 V2Ray transport，但 Xray 的全部 fallback、REALITY、特殊 transport 组合未必完全一一对应。

决策：

- POC 支持协议类型和常见 transport。
- 完整 Xray 配置转换另列迁移任务。

### 4. 重启中断

完整配置重启会断开现有连接。

决策：

- 熟人使用场景可接受。
- 后续再评估动态 API 或分节点滚动重启。

### 5. 节点数量

十个节点全互通为 90 条 directed links。

决策：

- 配置体积和管理复杂度可接受。
- 不做多跳，避免组合爆炸。

## 实施里程碑

### M0: Docker lab 手写配置

时间：2-3 天。

产物：

- `docker/singbox-poc/docker-compose.yml`
- 三个节点配置。
- 一个客户端配置。
- whoami 出口验证。

通过标准：

- Hysteria2 从 node-a 入，node-b 出。
- 改出口为 node-c 后，whoami 来源变化。

### M1: sing-box config builder

时间：4-6 天。

产物：

- `SingBoxConfigBuilder`
- 协议用户渲染器。
- 节点链路渲染器。
- 用户出口 route rule 渲染器。

通过标准：

- 从数据库 fixtures 生成 node-a/node-b/node-c 配置。
- JSON 可通过 `sing-box check -c config.json`。

### M2: Runtime 替换 POC

时间：3-5 天。

产物：

- `SingBoxCore`
- 进程启动/停止/重启/日志读取。
- `CORE_RUNTIME=singbox` 本机运行。

通过标准：

- `python main.py` 能启动 sing-box。
- 修改用户出口后重启并生效。

### M3: API + 简单 UI

时间：4-7 天。

产物：

- 用户出口节点 API。
- 节点链路 rebuild API。
- Dashboard 用户编辑中选择出口节点。

通过标准：

- 面板改用户出口后，Docker lab 出口行为变化。

### M4: 协议补齐

时间：5-8 天。

产物：

- VMess/VLESS/Trojan/Shadowsocks/Hysteria2/TUIC/AnyTLS inbound 生成。
- sing-box/Clash 订阅生成补齐。

通过标准：

- 每个协议至少一个 Docker lab 连通性用例通过。

### M5: 稳定化

时间：3-5 天。

产物：

- 配置 hash 避免无意义重启。
- 基础错误提示。
- README/部署说明。
- 粗略节点状态。

通过标准：

- 十节点配置生成不超时。
- 单用户出口切换流程可重复执行。

## 粗略工期

只做 POC：

```text
2-4 周
```

做到熟人可用：

```text
4-6 周
```

补完整协议订阅、迁移说明、基本 UI 和粗略统计：

```text
6-8 周
```

## POC 验收清单

- [x] sing-box Docker 镜像固定版本。
- [x] Docker lab 可以启动 3 个节点和 1 个客户端。
- [x] Hysteria2 node-link 可用。
- [x] 至少一个用户可从 node-a 入、node-b 出。
- [x] 切换出口后，whoami 来源节点变化。
- [x] VMess/VLESS/Trojan/Shadowsocks/Hysteria2/TUIC/AnyTLS 均至少通过一个入口连接测试。
- [x] 配置生成器输出可通过 `sing-box check`。
- [x] API 骨架可以生成 POC 拓扑、节点配置和客户端用例配置。
- [x] 最小 POC UI 提供出口节点选择、节点链路和核心配置提示。
- [x] sing-box/Clash 订阅生成已补 POC 协议覆盖。
- [x] 十节点配置生成并通过 `sing-box check`。
- [x] runtime smoke 覆盖 start/logs/restart/stop。
- [x] `CORE_RUNTIME=singbox python3 main.py` standalone smoke 可启动 sing-box。
- [x] 重启后配置生效。
- [x] 统计不可用时系统仍可正常使用。

实测结果记录在 `docker/singbox-poc/RESULTS.md`。
