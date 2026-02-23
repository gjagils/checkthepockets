init-env: ## Maak stack.env aan op basis van .env.example
	@if [ -f stack.env ]; then \
		echo "stack.env bestaat al — geen wijzigingen gemaakt."; \
	else \
		grep -v '^#' .env.example | grep -v '^$$' > stack.env; \
		echo "stack.env aangemaakt. Pas de waarden aan voor productie."; \
	fi
