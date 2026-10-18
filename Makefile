PYTHON ?= .venv/bin/python

.PHONY: install-dev lint format test coverage check run
install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt
lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
format:
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .
test:
	$(PYTHON) -m pytest
coverage:
	$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=xml
check: lint test
run:
	./run.sh
