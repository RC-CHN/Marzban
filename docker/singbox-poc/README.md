# sing-box POC Lab

This lab validates the sing-box POC design with Ubuntu 22.04 based containers.

It starts three sing-box nodes and a small HTTP echo service:

- `node-a`: entry node, routes test user `u1` to `node-b`.
- `node-b`: exit node for `node-a`, also routes `u1` to `node-c` when used as entry.
- `node-c`: exit node for `node-b`, routes `u1` to `node-a` when used as entry.
- `whoami`: returns the source IP seen by the destination service.
- `client`: temporary container used by test cases.

All node-to-node links use Hysteria2 with an internal CA and mTLS. Public entry protocols covered by the generator:

- `hysteria2`
- `tuic`
- `anytls`
- `vmess`
- `vless`
- `trojan`
- `shadowsocks`

## Run

```bash
./docker/singbox-poc/scripts/run-tests.sh
```

The script:

1. Generates public POC certs, node-link mTLS certs, and JSON configs under `docker/singbox-poc/generated/`.
2. Builds an Ubuntu 22.04 based POC image.
3. Checks the bootstrap script syntax and `check` command.
4. Runs `sing-box check` for all generated node and client configs.
5. Starts node containers and `whoami`.
6. Runs each client protocol through a local mixed inbound and verifies the source IP observed by `whoami`.

Expected remote-exit result:

```text
node-a entry -> node-b exit -> whoami sees 172.29.10.12
```

Expected direct result:

```text
node-a entry -> direct -> whoami sees 172.29.10.11
```

## Useful Commands

```bash
docker compose -f docker/singbox-poc/docker-compose.yml ps
docker compose -f docker/singbox-poc/docker-compose.yml logs -f node-a node-b node-c
docker compose -f docker/singbox-poc/docker-compose.yml down --remove-orphans
```

## POC UI

A minimal static control mock is available at `docker/singbox-poc/ui/index.html`.
It mirrors the M3 controls used by the lab: user exit-node selection, node
entry/exit flags, link port, generated link count, and active config hints.
