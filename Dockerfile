# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12

FROM python:$PYTHON_VERSION-slim AS build

ENV PYTHONUNBUFFERED=1

WORKDIR /code

RUN --mount=type=cache,id=marzban-runtime-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=marzban-runtime-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl unzip gcc python3-dev libpq-dev

COPY ./requirements.txt /code/
RUN --mount=type=cache,id=marzban-runtime-pip,target=/root/.cache/pip \
    python3 -m pip install --upgrade pip setuptools==80.9.0 \
    && pip install --upgrade -r /code/requirements.txt

FROM python:$PYTHON_VERSION-slim

ENV PYTHON_LIB_PATH=/usr/local/lib/python${PYTHON_VERSION%.*}/site-packages
WORKDIR /code

RUN rm -rf $PYTHON_LIB_PATH/*

COPY --from=build $PYTHON_LIB_PATH $PYTHON_LIB_PATH
COPY --from=build /usr/local/bin /usr/local/bin
COPY ./sing-box-1.13.14-linux-amd64/sing-box /usr/local/bin/sing-box

COPY . /code

RUN ln -s /code/marzban-cli.py /usr/bin/marzban-cli \
    && chmod 0755 /usr/local/bin/sing-box \
    && chmod +x /usr/bin/marzban-cli \
    && marzban-cli completion install --shell bash

CMD ["bash", "-c", "alembic upgrade head; python main.py"]
