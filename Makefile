.PHONY: help data up test lint build

help:
	@echo "make data   download the January 2026 Elexon window into data/"
	@echo "make up     run the stack locally (http://localhost:5173)"
	@echo "make test   run the Python test suite"
	@echo "make build  production build of the front end"

data:
	python3 scripts/fetch_data.py

up:
	docker compose up --build

test:
	cd backend && PYTHONPATH=. ELEXON_OFFLINE=1 DATA_DIR=../data python3 -m pytest tests -q

build:
	cd frontend && npm install && npm run build
