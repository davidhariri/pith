CONTAINER_NAME ?= pith-dev

.PHONY: run stop logs risk update help

run:
	./scripts/entrypoint.sh run

stop:
	@docker stop $(CONTAINER_NAME) >/dev/null 2>&1 && echo "stopped $(CONTAINER_NAME)" || echo "$(CONTAINER_NAME) is not running"
	@docker rm $(CONTAINER_NAME) >/dev/null 2>&1 || true

logs:
	@docker logs -f $(CONTAINER_NAME)

risk:
	./scripts/entrypoint.sh risk

update:
	./scripts/entrypoint.sh update

help:
	@echo "Commands:"
	@echo "  make run    - build image and run service in Docker (background)"
	@echo "  make stop   - stop the running container"
	@echo "  make logs   - tail container logs"
	@echo "  make update - rebuild Docker image from scratch"
	@echo "  make risk   - run service locally via uv (no Docker)"
