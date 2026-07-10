#!/usr/bin/env bash
set -euo pipefail

ruff check \
  app/core/singbox \
  app/models/singbox.py \
  app/routers/singbox.py \
  app/utils/rate_limit.py \
  config.py \
  main.py \
  marzban-cli.py \
  tests

python -m compileall -q \
  app/core \
  app/models \
  app/routers \
  app/utils \
  config.py \
  main.py \
  marzban-cli.py

python -m unittest discover -s tests -p 'test_*.py'
