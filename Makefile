.PHONY: up down seed seed-chat test lint scenario-biz scenario-ops

# Database demo chung (bo du lieu chat_v1) va database rieng cua kich ban nghiep vu.
# Kich ban nghiep vu xoa va seed lai database cua no, nen KHONG tro vao DEMO_DB.
DEMO_DB ?= shipaudit_demo
SCENARIO_DB ?= shipaudit_scenario

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
	python -m scenarios.biz.run --db $(SCENARIO_DB) --reset

scenario-ops:
	python -m scenarios.ops.run

# Bo du lieu demo chinh (generator/out/chat_v1): chuyen dinh dang, nap Atlas, doi soat, so voi labels.json
seed-chat:
	python -m generator.chat_v1 --db $(DEMO_DB) --reset
