SHELL := /bin/bash
BUILD_DIR ?= build
PYPNM_VERSION := $(shell sed -n 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)"/\1/p' pyproject.toml)
DEPLOY_VERSION ?= $(PYPNM_VERSION)

.PHONY: docker-up docker-down docker-logs deploy-bundle

## Build and run the development Docker stack from the repo root
docker-up:
	docker compose up -d --build

## Stop the development Docker stack and remove containers/volumes
docker-down:
	docker compose down --volumes

## Follow logs from the development Docker stack
docker-logs:
	docker compose logs -f pypnm-api

## Create the release-ready deploy bundle tarball
deploy-bundle:
	mkdir -p $(BUILD_DIR)
	tar -czf $(BUILD_DIR)/pypnm-deploy-$(DEPLOY_VERSION).tar.gz \
		-C deploy/docker README.md install.sh \
		config/system.json.template \
		compose/docker-compose.yml \
		compose/.env.example
	@echo "Created $(BUILD_DIR)/pypnm-deploy-$(DEPLOY_VERSION).tar.gz"
