PYTHON = venv/bin/python3
PLAYWRIGHT = venv/bin/playwright

.PHONY: setup scrape test

# Crear venv, instalar dependencias y bajar Chromium
setup:
	python3 -m venv venv
	venv/bin/pip install -q -r scraper/requirements.txt
	$(PLAYWRIGHT) install chromium
	@echo "Listo. Ahora podes correr: make scrape"

# Scrape completo
scrape:
	$(PYTHON) scraper/scraper.py

# Scrape rapido de prueba (1 pagina, 3 detalles)
test:
	$(PYTHON) scraper/scraper.py --test
