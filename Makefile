ARIXA_VENV ?= .venv
ARIXA_BIN := $(ARIXA_VENV)/bin
ARIXA := $(ARIXA_BIN)/arixa
ARLINT := $(ARIXA_BIN)/arlint
PYTEST := $(ARIXA_BIN)/pytest

ARIXA_SOURCES := $(shell find . -name '*.arixa' -print)

.PHONY: help venv bootstrap fmt fmt-check lint test e2e bundle-vscode bundle-toolchain sync-editor-tools verify-editor-sync all

help:
	@echo "Available targets:"
	@echo "  venv       - create virtualenv and install arixa in dev mode"
	@echo "  fmt        - format all .arixa sources in-place"
	@echo "  fmt-check  - check formatting of all .arixa sources"
	@echo "  lint       - run arixa linter on all .arixa sources"
	@echo "  test       - run arixa CLI tests and full pytest suite (auto-bootstraps .venv)"
	@echo "  e2e        - run e2e tests via 'arixa test --kind e2e' (if configured)"
	@echo "  bundle-vscode   - refresh bundled compiler snapshot used by VS Code extension"
	@echo "  bundle-toolchain - build portable compiler bundle into dist/toolchain/"
	@echo "  sync-editor-tools - automatically sync VS Code extension syntax with language changes (LSP imports directly from main project)"
	@echo "  verify-editor-sync - verify that editor tools are properly synchronized"
	@echo "  all        - fmt-check, lint, and test"

venv:
	python -m venv $(ARIXA_VENV)
	$(ARIXA_BIN)/python -m pip install -e ".[dev]"

bootstrap:
	@if [ ! -x "$(ARIXA)" ] || [ ! -x "$(PYTEST)" ]; then \
	  echo "Bootstrapping $(ARIXA_VENV) with project dev dependencies..."; \
	  python -m venv $(ARIXA_VENV); \
	  $(ARIXA_BIN)/python -m pip install -e ".[dev]"; \
	fi

fmt: bootstrap
	$(ARIXA) fmt $(ARIXA_SOURCES)

fmt-check: bootstrap
	$(ARIXA) fmt --check $(ARIXA_SOURCES)

lint: bootstrap
	@for f in $(ARIXA_SOURCES); do \
	  echo "lint $$f"; \
	  $(ARLINT) $$f || exit $$?; \
	done

test: bootstrap
	$(ARIXA) test
	$(PYTEST)

e2e: bootstrap
	$(ARIXA) test --kind e2e

bundle-vscode:
	python scripts/build_vscode_bundle.py

bundle-toolchain:
	python scripts/build_toolchain_bundle.py --layout portable --clean --output dist/toolchain

sync-editor-tools:
	python scripts/sync_editor_tools.py

verify-editor-sync:
	python scripts/verify_editor_sync.py

all: fmt-check lint test
