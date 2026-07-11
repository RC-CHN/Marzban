# sing-box bootstrap E2E

This stack builds one panel and bootstraps three Ubuntu 22.04 nodes through the
same script used by production nodes. It verifies public protocol ingress,
node-link mTLS, the selected exit node, pull sync, heartbeat reporting, and
legacy agent report compatibility.

## Fast development run

The default mode uses an Ubuntu 22.04 toolbox image with the test dependencies
preinstalled. Docker layer caches make repeated panel and toolbox builds cheap.

```bash
bash docker/singbox-bootstrap-e2e/scripts/run-tests.sh
```

To reuse images that have already been built:

```bash
E2E_SKIP_TOOLBOX_BUILD=1 \
E2E_SKIP_PANEL_BUILD=1 \
bash docker/singbox-bootstrap-e2e/scripts/run-tests.sh
```

## Clean-room run

Clean-room mode replaces the toolbox containers with plain `ubuntu:22.04`
containers. This intentionally reinstalls runtime dependencies and is slower,
but catches bootstrap assumptions hidden by the toolbox image.

```bash
E2E_CLEAN_ROOM=1 bash docker/singbox-bootstrap-e2e/scripts/run-tests.sh
```

## Proxy

Image builds and bootstrap downloads accept the same proxy variables:

```bash
E2E_HTTP_PROXY=http://192.168.44.2:10820 \
E2E_HTTPS_PROXY=http://192.168.44.2:10820 \
bash docker/singbox-bootstrap-e2e/scripts/run-tests.sh
```

GitHub Actions stores the toolbox, E2E panel, and production image BuildKit
caches in separate scopes so package caches from different base distributions
cannot contaminate each other.
