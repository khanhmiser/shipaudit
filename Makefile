.PHONY: up down seed test lint scenario-biz scenario-ops

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
