# Servicio de lecturas: backend

API en Python (FastAPI) con PostgreSQL 17. Carga lecturas desde archivos CSV y expone el resumen diario y el recorrido de cada dispositivo.

La interfaz web está en el repositorio [ejercicio-tecnico-frontend](https://github.com/Alfredo455/ejercicio-tecnico-frontend).

## Ejecución

Requiere Docker con Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

- **API:** `http://localhost:8000`
- **Documentación interactiva:** `http://localhost:8000/docs`
- **Guía para el frontend:** [`docs/API.md`](docs/API.md)

Si los puertos `5432` u `8000` están ocupados, cambia `DB_PORT` o `API_PORT` en `.env`.

## Carga de archivos

Los lotes no forman parte del proyecto. Se suben de a uno, en el orden en que llegaron, con `POST /batches`:

```bash
curl -F "file=@/ruta/a/lote_1.csv" http://localhost:8000/batches
curl -F "file=@/ruta/a/lote_2.csv" http://localhost:8000/batches
```

La respuesta informa las filas leídas, válidas y descartadas por motivo. La limpieza ocurre en el software: el CSV nunca se modifica ni se guarda.

También se puede cargar por comando desde tu máquina, con el entorno de [Tests](#tests) instalado y el archivo `.env`:

```bash
.venv/Scripts/python -m app.ingestion.load /ruta/a/lote_1.csv
```

- **Es idempotente:** un archivo con el mismo contenido no vuelve a aplicarse, aunque se cargue después de otro más nuevo.
- **Es atómica:** ante un error se revierte todo y el archivo se puede volver a cargar.
- **Vale la última lectura recibida:** dentro de un archivo gana la fila más abajo, y entre archivos gana el que llegó después.

## Estructura

| Ruta | Responsabilidad |
| :--- | :--- |
| `app/main.py` | Crea la aplicación y registra las rutas, CORS y errores |
| `app/core/` | Configuración, conexión y esquema de la base |
| `app/api/` | Rutas HTTP y formato de las respuestas |
| `app/services/` | Reglas de negocio: armado del resumen y del recorrido |
| `app/repositories/` | Consultas SQL, incluido el cálculo de sesiones |
| `app/ingestion/` | Validación de filas, lectura de CSV y carga en la base |
| `docs/` | Documentación de la API |
| `tests/` | Pruebas unitarias y de integración |

## Base de datos

El esquema está en `app/core/schema.sql` y se aplica cada vez que arranca la API. Solo crea lo que falta, así que no modifica tablas existentes: si cambias una tabla, recrea la base con `docker compose down -v`, lo que borra los datos cargados.

| Tabla | Contenido |
| :--- | :--- |
| `readings` | Una lectura por dispositivo e instante: la última recibida |
| `batches` | Archivos cargados, con su hash y contadores |
| `batch_rejections` | Filas descartadas de cada archivo, por motivo |

Las sesiones y los días no se guardan: se calculan al consultar, porque un dato atrasado puede cambiarlos.

## Tests

Requieren Python 3.11 o superior, el archivo `.env` y la base levantada. Usan una base aparte, `lecturas_test`, así que no tocan los datos cargados.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt  # En Linux o macOS: .venv/bin/python
.venv/Scripts/python -m pytest
```

## Configuración

| Variable | Uso |
| :--- | :--- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Credenciales de la base |
| `DB_PORT` | Puerto de la base publicado en tu máquina |
| `API_PORT` | Puerto de la API publicado en tu máquina |
| `CORS_ORIGINS` | Orígenes del frontend permitidos, separados por coma |
