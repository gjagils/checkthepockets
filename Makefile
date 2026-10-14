.PHONY: test lint cov check

test:  ## Alle tests (zelfde opdracht als de CI)
	python -m pytest tests/ --tb=short

lint:  ## Statische controle (ruff, zie pyproject.toml)
	python -m ruff check app tests alembic scripts

cov:  ## Tests met dekking (geen drempel)
	python -m pytest tests/ --tb=short --cov=app --cov-report=term-missing:skip-covered

check: lint test  ## Wat de CI ook doet
