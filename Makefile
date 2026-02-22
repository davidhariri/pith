.PHONY: run risk help

run:
	./scripts/entrypoint.sh run

risk:
	./scripts/entrypoint.sh risk

help:
	@echo "Commands:"
	@echo "  make run  - run inside Docker container (requires Docker)"
	@echo "  make risk - run locally via uv (no Docker)"
