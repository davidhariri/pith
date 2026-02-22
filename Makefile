.PHONY: run risk update help

run:
	./scripts/entrypoint.sh run

risk:
	./scripts/entrypoint.sh risk

update:
	./scripts/entrypoint.sh update

help:
	@echo "Commands:"
	@echo "  make run    - build image and run service in Docker"
	@echo "  make update - rebuild Docker image from scratch"
	@echo "  make risk   - run service locally via uv (no Docker)"
