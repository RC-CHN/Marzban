FROM ghcr.io/sagernet/sing-box:v1.13.14 AS singbox

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        dnsutils \
        iproute2 \
        iputils-ping \
        jq \
        netcat-openbsd \
        openssl \
        python3 \
        tcpdump \
    && rm -rf /var/lib/apt/lists/*

COPY --from=singbox /usr/local/bin/sing-box /usr/local/bin/sing-box

WORKDIR /poc

CMD ["sing-box", "version"]

