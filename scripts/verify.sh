#!/usr/bin/env bash
# DevFlow AI Demo 端到端验收(POSIX)。Windows 上请用 scripts/verify.ps1。
#
# 这是交付的唯一权威验收入口:容器健康 + 后端单测 + 前端单测 + 全链路 HTTP 验收。
set -uo pipefail
cd "$(dirname "$0")/.."

pass=0; fail=0
step() { echo; echo "==== $1 ===="; }
mark() { if [ "$1" -eq 0 ]; then echo "  [PASS] $2"; pass=$((pass+1)); else echo "  [FAIL] $2"; fail=$((fail+1)); fi }

step "1. 容器健康"
for svc in postgres etcd minio milvus backend frontend; do
  state=$(docker compose ps --format '{{.Service}}|{{.State}}' | grep "^$svc|" | cut -d'|' -f2)
  [ "$state" = "running" ]; mark $? "$svc running"
done

step "2. 后端单测(全 Mock,不联网)"
docker compose exec -T backend pytest -q
mark $? "pytest"

step "3. 前端单测"
docker compose exec -T frontend npm test --silent
mark $? "vitest"

step "4. 全链路 HTTP 验收"
docker compose cp scripts/verify_api.py backend:/app/_verify_api.py >/dev/null 2>&1
docker compose exec -T backend python /app/_verify_api.py
mark $? "verify_api"

echo
echo "==== 验收汇总: PASS=$pass FAIL=$fail ===="
[ "$fail" -eq 0 ] || exit 1