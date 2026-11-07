# Minimal Makefile for Mesly project
# Targets:
#   all             - installs pip requirements, initializes vendor submodules, and builds the extension
#   venv            - create a local virtualenv in .venv and install requirements into it
#   install-pip     - install pip requirements using system python
#   vendor          - init/update git submodules (vendor) if present
#   build-extension - run npm install and npm run build in src/extension
#   run             - run the Mesly application
#   clean           - remove common build artifacts

PY ?= python3
NPM ?= npm
EXT_DIR = src/extension
VENV_DIR = .venv

# List of vendored repositories to ensure present locally.
VENDOR_REPOS ?= neutts:https://github.com/neuphonic/neutts

.PHONY: all venv install-pip vendor build-extension run clean

all: install-pip vendor build-extension
	@echo "All done. Extension built and python requirements installed."

venv:
	@echo "Creating virtualenv in $(VENV_DIR) (if it already exists this will reuse it)..."
	$(PY) -m venv $(VENV_DIR)
	@echo "Activating venv and installing requirements..."
	. $(VENV_DIR)/bin/activate && python -m pip install --upgrade pip && python -m pip install -r requirements.txt
	@echo "Virtualenv setup complete. To activate: . $(VENV_DIR)/bin/activate"

install-pip:
	@echo "Installing pip requirements using $(PY)..."
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	@echo "Pip requirements installed."

vendor:
	@echo "Initializing/updating git submodules (vendor)..."
	@if [ -f .gitmodules ]; then \
		git submodule update --init --recursive; \
		echo "Git submodules initialized/updated."; \
	else \
		echo "No .gitmodules file found — nothing to do for vendor submodules."; \
	fi
	@echo "Ensuring vendored dependencies..."
	@mkdir -p vendor
	@for repo in $(VENDOR_REPOS); do \
		name=$${repo%%:*}; \
		url=$${repo#*:}; \
		dest=vendor/$${name}; \
		if [ -d $$dest ]; then \
			echo "$$dest already exists — skipping clone."; \
		else \
			echo "Cloning $$name from $$url into $$dest..."; \
			if git --version >/dev/null 2>&1; then \
				git clone --depth 1 $$url $$dest || { echo "Failed to clone $$url into $$dest"; exit 1; }; \
			else \
				echo "git not found; cannot clone $$url automatically"; exit 1; \
			fi; \
		fi; \
		if [ ! -f vendor/__init__.py ]; then printf "# vendor package\n" > vendor/__init__.py && echo "Created vendor/__init__.py"; fi; \
		if [ -d $$dest ] && [ ! -f $$dest/__init__.py ]; then printf "# $$name package (vendored)\n" > $$dest/__init__.py && echo "Created $$dest/__init__.py"; fi; \
	done

build-extension:
	@echo "Building browser extension in $(EXT_DIR)..."
	@if [ -d $(EXT_DIR) ] && [ -f $(EXT_DIR)/package.json ]; then \
		cd $(EXT_DIR) && $(NPM) install && { $(NPM) run build || $(NPM) run build --if-present; }; \
		echo "Extension build finished."; \
	else \
		echo "Extension directory or package.json not found at $(EXT_DIR). Skipping build."; \
	fi

run:
	@echo "Running Mesly..."
	$(PY) main.py

clean:
	@echo "Cleaning common build artifacts..."
	@rm -rf $(EXT_DIR)/dist || true
	@rm -rf $(EXT_DIR)/build || true
	@rm -rf build || true
	@echo "Clean complete."
