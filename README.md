# Inversiones Montevideo

Dashboard personal para encontrar apartamentos en Montevideo aptos para inversion (alquiler), con presupuesto total hasta U$S 100.000.

## Estructura

```
inversiones/
├── .github/workflows/scrape.yml   # GitHub Actions: cron diario + manual
├── scraper/
│   ├── scraper.py                 # Scraper Python (MercadoLibre + Infocasas)
│   └── requirements.txt
├── data/
│   └── apartments.json            # Datos generados (actualizado por el scraper)
├── index.html                     # Frontend (GitHub Pages)
├── style.css
└── app.js
```

## Setup inicial

### 1. Instalar dependencias Python

```bash
cd scraper
pip install -r requirements.txt
```

### 2. Probar el scraper (modo rapido)

```bash
python scraper/scraper.py --test
```

Scrapea solo 1-2 paginas y 3 detalles para verificar que todo funciona.

### 3. Scrape completo

```bash
python scraper/scraper.py
```

Puede tardar 10-30 minutos segun la cantidad de listados (visita cada pagina de detalle).
Los datos se guardan en `data/apartments.json`.

### 4. Ver la web localmente

Abrir `index.html` en el navegador. Si hay errores de CORS al cargar el JSON, usar un servidor local:

```bash
# Python
python -m http.server 8080
# o con npx
npx serve .
```

Luego abrir http://localhost:8080

### 5. Publicar en GitHub Pages

1. Hacer push al repo:
   ```bash
   git add .
   git commit -m "init: proyecto inversiones MVD"
   git push
   ```

2. En GitHub: **Settings → Pages → Source: Deploy from a branch → Branch: main / (root)**

3. La web estara disponible en: `https://chematos.github.io/inversiones`

## Actualizacion de datos

### Automatica (diaria)
GitHub Actions ejecuta el scraper automaticamente todos los dias a las 8am hora Uruguay.
Requiere que GitHub Pages este habilitado y el repo tenga permisos de escritura en Actions
(Settings → Actions → General → Workflow permissions → Read and write permissions).

### Manual desde GitHub
1. Ir a: https://github.com/chematos/inversiones/actions/workflows/scrape.yml
2. Click en **"Run workflow"**

### Manual local
```bash
python scraper/scraper.py
git add data/apartments.json
git commit -m "chore: actualizar datos"
git push
```

## Criterios de inversion

- **Precio maximo buscado**: U$S 88.000 (dejando ~12% para gastos de escritura + colchon de refaccion)
- **Zonas excluidas**: Alta inseguridad (Casavalle, Borro, Manga, Marconi, Peñarol, Maroñas, etc.)
- **Score**: basado en rentabilidad anual bruta. 10% = score 100.
- **Rentabilidad**: estimada con alquileres medianos por zona. Se puede ajustar en `ZONE_RENT_USD` del scraper.

## Ajustar estimaciones de alquiler

Si los valores de alquiler en `scraper/scraper.py` quedan desactualizados, editar el diccionario `ZONE_RENT_USD` con valores actuales de mercado.

## Agregar Infocasas correctamente

Si Infocasas no devuelve datos, ejecutar en modo test y revisar el archivo `scraper/debug_infocasas.json` que se genera automaticamente. Ahi se puede inspeccionar la estructura de `__NEXT_DATA__` y ajustar las rutas en la funcion `scrape_infocasas()`.
