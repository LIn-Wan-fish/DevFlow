.PHONY: up down restart logs ps build test migrate seed index eval verify shell fresh

up:        ; docker compose up -d --build
down:      ; docker compose down
restart:   ; docker compose restart backend frontend
logs:      ; docker compose logs -f --tail=100
ps:        ; docker compose ps

build:     ; docker compose build

# 单测:全 Mock,不联网
test:      ; docker compose exec -T backend pytest -v

migrate:   ; docker compose exec -T backend alembic upgrade head
seed:      ; docker compose exec -T backend python -m app.db.seed --repo 1
index:     ; docker compose exec -T backend python -m app.rag.indexer --repo 1
eval:      ; docker compose exec -T backend python -m app.eval.cli --dataset tests/data/eval_cases.json

verify:    ; ./scripts/verify.sh
shell:     ; docker compose exec backend bash

# 冷启动一次到底:验收要求「冷启动一次通过」
fresh:     ; docker compose down -v && $(MAKE) up && sleep 40 && $(MAKE) migrate && $(MAKE) seed && $(MAKE) index