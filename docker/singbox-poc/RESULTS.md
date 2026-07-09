# sing-box POC Results

Date: 2026-07-09

## Environment

The POC image is built from Ubuntu 22.04 and copies the sing-box binary from the pinned upstream image.

Verified inside the image:

```text
PRETTY_NAME="Ubuntu 22.04.5 LTS"
sing-box version 1.13.14
```

## Command

```bash
./docker/singbox-poc/scripts/run-tests.sh
```

The command completed successfully after:

- generating node and client configs through `app/core/singbox/config.py`
- generating a node-link CA, server certificate, and client certificate for mTLS
- checking the bootstrap script syntax and `check` command
- running `sing-box check` for all node configs
- running `sing-box check` for all client configs
- running `sing-box check` for the generated sing-box subscription
- checking generated Clash/Mihomo YAML includes all POC protocols
- running `sing-box check` for ten generated full-mesh node configs
- running runtime smoke for start/logs/restart/stop
- running `CORE_RUNTIME=singbox python3 main.py` standalone smoke
- starting three sing-box node containers and a `whoami` HTTP service
- testing each client protocol through a local mixed inbound
- swapping `node-a` config, restarting the container, and verifying the new exit

## Verified Cases

| Case | Entry | Protocol | Expected exit | Observed source |
|---|---|---|---|---|
| `hysteria2` | `node-a` | Hysteria2 | `node-b` | `172.29.10.12` |
| `tuic` | `node-a` | TUIC | `node-b` | `172.29.10.12` |
| `anytls` | `node-a` | AnyTLS | `node-b` | `172.29.10.12` |
| `vmess` | `node-a` | VMess | `node-b` | `172.29.10.12` |
| `vless` | `node-a` | VLESS | `node-b` | `172.29.10.12` |
| `trojan` | `node-a` | Trojan | `node-b` | `172.29.10.12` |
| `shadowsocks` | `node-a` | Shadowsocks 2022 | `node-b` | `172.29.10.12` |
| `hysteria2-direct` | `node-a` | Hysteria2 | `node-a` | `172.29.10.11` |
| `hysteria2-node-b` | `node-b` | Hysteria2 | `node-c` | `172.29.10.13` |
| `hysteria2-node-c` | `node-c` | Hysteria2 | `node-a` | `172.29.10.11` |
| `restart-apply` | `node-a` | Hysteria2 | `node-c` | `172.29.10.13` |

## Notes

- Node-to-node links use Hysteria2 with an internal CA and mTLS.
- Public entry protocols include the original Xray-era protocols plus Hysteria2, TUIC, and AnyTLS.
- The POC validates one-hop arbitrary entry/exit behavior only.
- Public client entry tests intentionally use self-signed TLS with client-side `insecure: true`.
- Node-to-node link configs do not use `insecure: true`.
- Per-user traffic accounting is not validated in this POC; billing remains intentionally approximate.
- A minimal static POC control UI exists at `docker/singbox-poc/ui/index.html`.
