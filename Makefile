# ForwardBin Hybrid Makefile
.PHONY: all build install restart status clean

CARGO := $(shell which cargo 2>/dev/null || echo $(HOME)/.cargo/bin/cargo)

all: build

build:
	@echo "🦀 Building Rust core (release)..."
	@PATH="$(HOME)/.cargo/bin:$(PATH)" $(CARGO) build --release

install: build
	@echo "🚀 Installing ForwardBin..."
	@./install.sh

uninstall:
	@echo "🛑 Uninstalling ForwardBin..."
	@./uninstall.sh

restart:
	@echo "🔄 Restarting ForwardBin services..."
	@systemctl --user restart forwardbin-ui.service forwardbin-daemon.service

status:
	@systemctl --user status forwardbin-ui.service forwardbin-daemon.service --no-pager

clean:
	@PATH="$(HOME)/.cargo/bin:$(PATH)" $(CARGO) clean
	@find . -name "__pycache__" -exec rm -rf {} +
