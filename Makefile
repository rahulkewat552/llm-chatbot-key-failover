.PHONY: up down logs test

up:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example - add real keys to LLM_API_KEYS, then run make up again." && exit 1)
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000   Backend: http://localhost:8000/health"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd backend && pip install -r requirements-dev.txt && python -m pytest
