# Common tasks (macOS/Linux/Git Bash with make). Windows PowerShell: see plan.md section 3.
SHELL := /bin/bash
-include .env
export

.PHONY: help setup db-up data load prices test run deploy-setup deploy-db deploy-app

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/ -/'

setup:           ## create virtualenv and install packages
	python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

db-up:           ## start local PostgreSQL 16 in Docker
	docker compose up -d db

data:            ## download Cricsheet IPL JSON into data/raw/ipl_json
	.venv/bin/python -m etl.download_data

load:            ## (re)build schema and load all data - destroys local data
	.venv/bin/python -m etl.load_cricsheet --reset

prices:          ## re-match data/sources/ipl_2026_squads.csv -> data/contracts_prices.csv (then `make load`)
	.venv/bin/python -m etl.build_contract_prices

test:            ## run tests against the local database
	.venv/bin/pytest -q

run:             ## run the web app on http://localhost:8080
	.venv/bin/flask --app main run --debug --port 8080

deploy-setup:    ## one-time Google Cloud setup (needs deploy/gcp.env)
	bash deploy/gcp_setup.sh

deploy-db:       ## copy the local database to Cloud SQL
	bash deploy/push_db.sh

deploy-app:      ## deploy the web app to App Engine
	bash deploy/deploy_app.sh
