ASTRA_VENV ?= .venv
ASTRA_BIN := $(ASTRA_VENV)/bin
ASTRA := $(ASTRA_BIN)/astra
ASTLINT := $(ASTRA_BIN)/astlint
PYTEST := $(ASTRA_BIN)/pytest

ASTRA_SOURCES := $(shell find . -name '*.astra' -print)

.PHONY: help venv fmt fmt-check lint test e2e sync-runtime clean all

help:
	@echo "Available targets:"
	@echo "  venv       - create virtualenv and install astra in dev mode"
	@echo "  fmt        - format all .astra sources in-place"
	@echo "  fmt-check  - check formatting of all .astra sources"
	@echo "  lint       - run astra linter on all .astra sources"
	@echo "  test       - run astra CLI tests and full pytest suite"
	@echo "  e2e        - run e2e tests via 'astra test --kind e2e' (if configured)"
	@echo "  sync-runtime - sync bundled runtime asset from runtime/llvm_runtime.c"
	@echo "  all        - fmt-check, lint, and test"

venv:
	python -m venv $(ASTRA_VENV)
	$(ASTRA_BIN)/python -m pip install -e ".[dev]"

fmt:
	$(ASTRA) fmt $(ASTRA_SOURCES)

fmt-check:
	$(ASTRA) fmt --check $(ASTRA_SOURCES)

lint:
	@for f in $(ASTRA_SOURCES); do \
	  echo "lint $$f"; \
	  $(ASTLINT) $$f || exit $$?; \
	done

test:
	$(ASTRA) test
	$(PYTEST)

e2e:
	$(ASTRA) test --kind e2e

all: fmt-check lint test



sync-runtime:
	python scripts/sync_runtime_asset.py


clean:
	rm -rf .build .astra-cache.json .pytest_cache
