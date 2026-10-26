.PHONY: up down seed seed-chat test lint scenario-biz scenario-ops

up:
	docker compose up --build

down:
	docker compose down

seed:
	python -m generator.seed --source synthetic

test:
	pytest -q

lint:
	python -m compileall -q app core common contracts generator pipelines ui

scenario-biz:
	python -m scenarios.biz.run

scenario-ops:
	python -m scenarios.ops.run

# Bo du lieu demo chinh (generator/out/chat_v1): chuyen dinh dang, nap Atlas, doi soat, so voi labels.json
seed-chat:
	python -m generator.chat_v1 --db shipaudit_b_chat_v1 --reset
