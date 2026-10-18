# Docker Compose v2 ist der Default. Mit Podman stattdessen:
#   make COMPOSE="podman-compose" DOCKER=podman dev
COMPOSE ?= docker compose
DOCKER  ?= docker

.PHONY: dev down db-reset import-osm

dev:
	$(COMPOSE) up

down:
	$(COMPOSE) down

# Setzt DB zurueck (und entfernt auch heruntergeladene BRouter-Segmente)
db-reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d db

# Import: make import-osm FILE=/absoluter/pfad/datei.osm.pbf
import-osm:
	@test -n "$(FILE)" || (echo "Usage: make import-osm FILE=/absoluter/pfad/datei.osm.pbf"; exit 1)
	$(COMPOSE) up -d db
	$(DOCKER) run --rm --network comoot \
		-v "$(CURDIR)/osm2pgsql_flex.lua":/config.lua:ro \
		-v "$(FILE)":/data.osm.pbf:ro \
		iboates/osm2pgsql:2.1.1 \
		--create --output=flex --style=/config.lua \
		--database=postgresql://comoot:comoot@db:5432/comoot \
		/data.osm.pbf
	$(COMPOSE) exec -T db psql -U comoot -d comoot < schema.sql
