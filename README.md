# Inventory Microservice

Microservicio de inventario para la plataforma Bazaar. Gestiona el stock de productos de forma atómica y expone una API REST interna consumida por otros microservicios de la plataforma. Construido con FastAPI y PostgreSQL.

## Tabla de contenidos

- [Stack](#stack)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Despliegue](#despliegue)
- [Endpoints](#endpoints)
  - [Health](#health)
  - [Stock](#stock)
  - [Formato de errores](#formato-de-errores)
- [Arquitectura en capas](#arquitectura-en-capas)
- [Tests](#tests)

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic, SQLAlchemy |
| Base de datos | PostgreSQL (configurable por env vars) |
| Contenedor | Docker (multi-stage, non-root) |
| Orquestación | Kubernetes (DigitalOcean) |
| CI/CD | GitHub Actions → GHCR → DOKS |

## Estructura del proyecto

```
├── src/
│   ├── api/
│   │   ├── controllers/        # Cableado de dependencias y mapeo request/response
│   │   │   └── stock.py        # StockController: instancia repo y servicio, convierte schemas a DTOs
│   │   ├── routers/            # Registro de rutas — solo delegan al controller
│   │   │   └── stock.py        # Rutas de /internal/products/*
│   │   ├── exception_handlers.py  # Handlers RFC 7807 para excepciones de dominio
│   │   └── health.py           # /livez y /readyz
│   ├── core/                   # Concerns transversales
│   │   ├── config.py           # Configuración desde variables de entorno
│   │   ├── database.py         # Engine, sesión, base declarativa y retry de conexión
│   │   ├── dependencies.py     # DbSession (Depends reutilizable)
│   │   ├── logging.py          # Configuración de logging estructurado
│   │   └── utils.py            # Funciones utilitarias (utc_now)
│   ├── dtos.py                 # Data Transfer Objects internos (dataclasses sin validación)
│   ├── exceptions/             # Excepciones de dominio
│   │   └── stock.py            # StockNotFound, InsufficientStock
│   ├── models/                 # Entidades SQLAlchemy
│   │   └── stock.py            # Stock (ORM)
│   ├── repositories/           # Acceso a datos — único lugar que usa Session
│   │   └── stock.py            # StockRepository: find_by_id, find_by_ids, create, save, delete, reserve
│   ├── schemas/                # Contratos Pydantic de la API
│   │   ├── stock.py            # Request/response schemas de stock
│   │   └── error.py            # ErrorResponse (RFC 7807)
│   ├── services/               # Lógica de negocio pura
│   │   └── stock.py            # StockService: register, delete, get, update, reserve, release
│   └── main.py                 # Punto de entrada, registro de routers y exception handlers
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   └── test_stock.py
├── scripts/
│   ├── run_tests.sh            # Wrapper para correr tests (Linux/macOS)
│   └── run_tests.ps1           # Wrapper para correr tests (Windows)
├── k8s/
│   ├── app-deployment.yaml     # Deployment del microservicio
│   ├── app-service.yaml        # Service (ClusterIP) del microservicio
│   ├── db-deployment.yaml      # Deployment de PostgreSQL
│   ├── db-service.yaml         # Service (ClusterIP) de PostgreSQL
│   ├── db-pvc.yaml             # PersistentVolumeClaim para la BD
│   └── secret.yaml             # ⚠️ Template — NO commitear valores reales
├── .github/workflows/
│   ├── ci-dev.yml              # Pipeline de CI en rama dev (lint + tests)
│   └── deploy.yml              # Pipeline de deploy a DOKS en push a main
├── Dockerfile                  # Imagen de producción
├── Dockerfile.test             # Imagen para correr tests
├── docker-compose.test.yml     # Levanta PostgreSQL + test runner
├── pyproject.toml              # Configuración de pytest y coverage
├── requirements.txt
└── .env.example
```

## Despliegue

El microservicio se despliega automáticamente en DigitalOcean Kubernetes (DOKS) en cada push a `main` a través del workflow de GitHub Actions (`deploy.yml`). El pipeline construye la imagen Docker, la publica en GHCR y aplica los manifiestos de `k8s/`.

Este servicio es **interno** — no está expuesto a través del gateway público. Es consumido por otros microservicios de la plataforma directamente dentro del cluster.

## Endpoints

### Health

| Método | Path | Descripción | Respuesta exitosa |
|--------|------|-------------|-------------------|
| `GET` | `/livez` | Liveness probe — proceso vivo | `200 {"status": "alive"}` |
| `GET` | `/readyz` | Readiness probe — BD alcanzable | `200 {"status": "ready"}` / `503 {"status": "unavailable"}` |

---

### Stock

Todos los endpoints de stock tienen el prefijo `/internal/products`.

#### `POST /internal/products/{id}/stock` — Registrar stock inicial

Se llama cuando se registra un nuevo producto en la plataforma.

**Body JSON:**

| Campo | Tipo | Restricciones |
|-------|------|---------------|
| `quantity` | int | ≥ 0 |

**Respuesta `201`:**
```json
{
  "data": {
    "product_id": "uuid",
    "quantity": 10,
    "updated_at": "2024-01-01T00:00:00Z"
  }
}
```

---

#### `DELETE /internal/products/{id}/stock` — Eliminar stock

Se llama cuando un producto es eliminado de la plataforma.

**Respuesta `204`:** sin contenido.  
**Respuesta `404`:** si no existe entrada de stock para el producto.

---

#### `GET /internal/products/{id}/stock` — Consultar stock

Devuelve el stock actual de un producto.

**Respuesta `200`:** objeto con `product_id`, `quantity` y `updated_at`.  
**Respuesta `404`:** si no existe entrada de stock para el producto.

---

#### `POST /internal/products/stocks` — Consulta batch de stock

Devuelve el stock de múltiples productos en una sola llamada. Los IDs que no tienen entrada de stock se omiten del resultado.

**Body JSON:**
```json
{ "product_ids": ["uuid-1", "uuid-2"] }
```

**Respuesta `200`:**
```json
{
  "data": {
    "uuid-1": 10,
    "uuid-2": 0
  }
}
```

---

#### `PUT /internal/products/{id}/stock` — Actualizar stock

Reemplaza el nivel de stock de un producto (ajuste manual).

**Body JSON:**

| Campo | Tipo | Restricciones |
|-------|------|---------------|
| `quantity` | int | ≥ 0 |

**Respuesta `200`:** objeto con el stock actualizado.  
**Respuesta `404`:** si no existe entrada de stock para el producto.

---

#### `POST /internal/products/{id}/stock/reserve` — Reservar stock

Decrementa el stock de forma atómica. Usa un único `UPDATE … WHERE quantity >= :qty` para manejar correctamente reservas concurrentes sin race conditions.

**Body JSON:**

| Campo | Tipo | Restricciones |
|-------|------|---------------|
| `quantity` | int | ≥ 1 |

**Respuesta `200`:** objeto con el stock resultante.  
**Respuesta `404`:** si no existe entrada de stock para el producto.  
**Respuesta `409`:** si el stock disponible es insuficiente.

---

#### `POST /internal/products/{id}/stock/release` — Liberar stock reservado

Restaura unidades previamente reservadas (se usa al cancelar una orden).

**Body JSON:**

| Campo | Tipo | Restricciones |
|-------|------|---------------|
| `quantity` | int | ≥ 1 |

**Respuesta `200`:** objeto con el stock resultante.  
**Respuesta `404`:** si no existe entrada de stock para el producto.

---

### Formato de errores

Todos los errores de dominio siguen [RFC 7807 Problem Details](https://www.rfc-editor.org/rfc/rfc7807) con `Content-Type: application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Insufficient Stock",
  "status": 409,
  "detail": "Product 550e8400-e29b-41d4-a716-446655440000 has only 2 units available.",
  "instance": "/internal/products/550e8400-e29b-41d4-a716-446655440000/stock/reserve"
}
```

| Excepción | HTTP |
|-----------|------|
| `StockNotFound` | `404 Not Found` |
| `InsufficientStock` | `409 Conflict` |

## Arquitectura en capas

El proyecto sigue una arquitectura en capas con dependencias unidireccionales:

```
HTTP Request
    │
    ▼
Router          — registra rutas, delega al controller
    │
    ▼
Controller      — instancia Repository y Service; convierte schemas → DTOs
    │
    ▼
Service         — lógica de negocio pura; lanza excepciones de dominio
    │
    ▼
Repository      — único lugar que construye queries SQL
    │
    ▼
PostgreSQL
```

**Regla de dependencias:** cada capa solo conoce a la inmediatamente inferior. El servicio no importa nada de `src.schemas` ni de FastAPI. Los routers no tienen lógica de negocio ni acceso a base de datos.

**DTOs (`src/dtos.py`):** dataclasses sin validación que transportan datos entre el controller y el servicio. La validación ocurre en los schemas de Pydantic antes de construir el DTO.

**Excepciones de dominio (`src/exceptions/stock.py`):** el servicio lanza `StockNotFound` e `InsufficientStock` en lugar de devolver valores especiales. `main.py` registra handlers globales que serializan estas excepciones a `application/problem+json` según RFC 7807.

**Reserva atómica:** el método `StockRepository.reserve()` ejecuta un único `UPDATE stocks SET quantity = quantity - :qty WHERE product_id = :id AND quantity >= :qty`. Si 0 filas son afectadas, el servicio determina si la causa es stock insuficiente (409) o producto inexistente (404). Este diseño evita cualquier race condition en checkouts concurrentes.

## Tests

Los tests corren contra una **base de datos PostgreSQL real** usando Docker Compose. No se usa mocking.

El archivo `docker-compose.test.yml` levanta:
1. Un contenedor **PostgreSQL 16** como base de datos.
2. Un contenedor **test-runner** que ejecuta `pytest` contra esa base de datos.

### Correr los tests

```bash
# Linux / macOS
./scripts/run_tests.sh

# Windows (PowerShell)
.\scripts\run_tests.ps1

# O directamente con docker compose
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit

# Cleanup
docker compose -f docker-compose.test.yml down -v
```

### Correr los tests localmente (con coverage)

Requiere una instancia de PostgreSQL corriendo (por ejemplo, el contenedor `db` del `docker-compose.yml`):

```bash
# 1. Levantar solo la base de datos
docker compose up db -d

# 2. Correr pytest con las variables de entorno
DB_HOST=localhost DB_PORT=5432 DB_USER=postgres DB_PASSWORD=postgres DB_NAME=inventory_db \
  pytest tests/ -v --cov=src --cov-report=term-missing

# 3. Bajar la base de datos
docker compose down
```

### CI/CD

**`ci-dev.yml`** — corre en cada push/PR a `dev`:

| Job | Descripción |
|-----|-------------|
| `lint` | Ruff sobre `src/` y `tests/` |
| `sast` | Bandit (análisis estático de seguridad) sobre `src/` |
| `test` | Tests contra PostgreSQL real vía Docker Compose |
