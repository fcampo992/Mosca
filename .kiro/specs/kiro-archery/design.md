# Documento de Diseño — KiroArchery

## Overview

KiroArchery es una aplicación web mobile-first construida con Flask (Python 3.12+) y Turso (libSQL/SQLite Edge) para la gestión integral de torneos de arquería en tiempo real. La arquitectura es monolítica con responsabilidades claramente delimitadas en módulos de Python, plantillas Jinja2 y assets de frontend servidos por Flask.

El sistema atiende tres perfiles de usuario:
- **Organizador** — gestiona torneos, categorías y arqueros desde un panel de administración.
- **Arquero** — se autentica con PIN de 4 dígitos y carga sus flechas mediante teclado táctil.
- **Espectador** — consulta el leaderboard en vivo sin autenticación.

### Flujo de datos de alto nivel

```
Arquero (celular)
    │  POST /scores  (flecha)
    ▼
Flask Route → Archer_Module → DB_Module (Turso/SQLite)
    │
    └─► Leaderboard_Module ──SSE──► Espectadores (navegador)
```

---

## Architecture

### Patrón general

Aplicación Flask con estructura de paquetes Python, sin frameworks de frontend pesados. Las vistas se sirven como plantillas Jinja2; la interactividad del cliente se maneja con Alpine.js (CDN) y JavaScript vanilla. Chart.js (CDN) renderiza gráficos estadísticos.

```
archer/
├── app.py                  # Factory de la aplicación Flask
├── config.py               # Lectura de variables de entorno
├── db.py                   # DB_Module — conexión única a Turso/SQLite
├── modules/
│   ├── admin.py            # Admin_Module — torneos, categorías, arqueros
│   ├── archer.py           # Archer_Module — autenticación PIN, puntuaciones
│   ├── leaderboard.py      # Leaderboard_Module — SSE, clasificación
│   └── stats.py            # Stats_Module — estadísticas y ranking global
├── routes/
│   ├── admin_routes.py     # Blueprint /admin
│   ├── archer_routes.py    # Blueprint /archer
│   ├── leaderboard_routes.py # Blueprint /leaderboard
│   └── stats_routes.py     # Blueprint /stats
├── templates/
│   ├── base.html
│   ├── admin/
│   ├── archer/
│   ├── leaderboard/
│   └── stats/
└── static/
    └── (assets estáticos mínimos)
```

### Máquina de estados del Torneo

```
┌─────────┐   activar   ┌────────┐   finalizar   ┌──────────┐
│ created │────────────►│ active │──────────────►│ finished │
└─────────┘             └────────┘               └──────────┘
      ▲                      │
      └──── ✗ no permitido ──┘  (revertir a created desde active/finished: prohibido)
```

Transiciones válidas: `created → active`, `active → finished`.  
Transiciones inválidas: `finished → *`, `active → created`.

### Flujo SSE del Leaderboard

```
Cliente (EventSource)          Flask SSE endpoint
       │                              │
       │── GET /leaderboard/stream ──►│
       │◄── estado inicial completo ──│
       │                              │
       │           (flecha guardada)  │
       │◄── evento "leaderboard" ─────│  ≤ 2 seg
       │                              │
       │         cada 30 seg          │
       │◄── evento "heartbeat" ───────│
```

---

## Components and Interfaces

### DB_Module (`db.py`)

Responsable de establecer y proveer la única instancia de conexión durante el ciclo de vida de la aplicación.

```python
def get_connection() -> Connection:
    """Retorna la conexión activa (Turso o SQLite). Singleton."""

def init_db(conn: Connection) -> None:
    """Ejecuta los CREATE TABLE IF NOT EXISTS para las 5 tablas."""
```

**Decisión de diseño:** Se utiliza el patrón singleton almacenando la conexión en `app.config['DB_CONN']` durante `create_app()`. Esto evita reconexiones costosas por request y es compatible con el threading de Flask en modo desarrollo (un worker).

### Admin_Module (`modules/admin.py`)

```python
# Torneos
def create_tournament(name: str, date: str) -> dict
def list_tournaments() -> list[dict]
def change_tournament_status(tournament_id: str, new_status: str) -> dict

# Categorías
def create_category(tournament_id: str, bow_type: str, distance: str, gender: str) -> dict
def list_categories(tournament_id: str) -> list[dict]

# Arqueros
def create_archer(name: str, pin: str) -> dict
def list_archers() -> list[dict]
def enroll_archer(archer_id: str, tournament_id: str, category_id: str) -> dict
```

### Archer_Module (`modules/archer.py`)

```python
def authenticate_pin(pin: str) -> dict | None
def get_active_tournament(archer_id: str) -> dict | None
def save_arrow(archer_id: str, tournament_id: str,
               round_number: int, end_number: int,
               arrow_val: str) -> dict
def get_end_summary(archer_id: str, tournament_id: str,
                    round_number: int, end_number: int) -> dict
def get_accumulated_points(archer_id: str, tournament_id: str) -> int
```

**Bloqueo por intentos fallidos:** Se mantiene en memoria (`dict` en el módulo) un registro `{pin: (intentos, timestamp_bloqueo)}`. No se persiste en DB para minimizar escrituras; se resetea si el proceso reinicia (comportamiento aceptable para la escala del sistema).

### Leaderboard_Module (`modules/leaderboard.py`)

```python
def compute_leaderboard(tournament_id: str) -> list[dict]
def broadcast_update(tournament_id: str) -> None
def sse_stream(tournament_id: str) -> Generator
```

**Decisión de diseño:** Se usa una cola en memoria (`queue.Queue`) por torneo para desacoplar la escritura de flechas del broadcasting SSE. Al guardar una flecha, `Archer_Module` llama a `broadcast_update()` que encola la señal; el generador SSE la consume y recalcula el leaderboard antes de emitir.

```
scores.save_arrow()
    └─► leaderboard.broadcast_update(tournament_id)
            └─► queue.put(tournament_id)
                    └─► sse_stream generator ──► response SSE
```

### Stats_Module (`modules/stats.py`)

```python
def tournament_stats(tournament_id: str, archer_id: str | None = None) -> dict
def archer_trend(archer_id: str) -> list[dict]
def global_ranking() -> list[dict]
```

---

## Data Models

### Esquema de base de datos

```sql
CREATE TABLE IF NOT EXISTS archers (
    id      TEXT PRIMARY KEY,          -- UUID v4
    pin     TEXT UNIQUE NOT NULL,      -- 4 dígitos numéricos
    name    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tournaments (
    id      TEXT PRIMARY KEY,          -- UUID v4
    name    TEXT NOT NULL,
    date    TEXT NOT NULL,             -- YYYY-MM-DD
    status  TEXT CHECK(status IN ('created','active','finished')) DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id            TEXT PRIMARY KEY,    -- UUID v4
    tournament_id TEXT NOT NULL REFERENCES tournaments(id),
    bow_type      TEXT NOT NULL,       -- Recurvo | Compuesto | Raso
    distance      TEXT NOT NULL,       -- 70m | 50m | 18m | …
    gender        TEXT NOT NULL        -- Masculino | Femenino | Mixto
);

CREATE TABLE IF NOT EXISTS registrations (
    id            TEXT PRIMARY KEY,    -- UUID v4
    tournament_id TEXT NOT NULL REFERENCES tournaments(id),
    archer_id     TEXT NOT NULL REFERENCES archers(id),
    category_id   TEXT NOT NULL REFERENCES categories(id),
    UNIQUE (tournament_id, archer_id, category_id)
);

CREATE TABLE IF NOT EXISTS scores (
    id            TEXT PRIMARY KEY,    -- UUID v4
    tournament_id TEXT NOT NULL REFERENCES tournaments(id),
    archer_id     TEXT NOT NULL REFERENCES archers(id),
    round_number  INTEGER NOT NULL,
    end_number    INTEGER NOT NULL,
    arrow_val     TEXT NOT NULL,       -- "X"|"10"|"9"|…|"1"|"M"
    points        INTEGER NOT NULL,    -- X→10, 10→10, …, M→0
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Nota:** Se agrega `UNIQUE (tournament_id, archer_id, category_id)` en `registrations` para garantizar la restricción de inscripción única a nivel de base de datos, como segunda línea de defensa.

### Mapeo de valores de flecha a puntos

| arrow_val | points |
|-----------|--------|
| X         | 10     |
| 10        | 10     |
| 9–1       | 9–1    |
| M         | 0      |

### Estructura de respuestas JSON

**Leaderboard event payload:**
```json
{
  "tournament_id": "uuid",
  "categories": [
    {
      "category_id": "uuid",
      "bow_type": "Recurvo",
      "distance": "70m",
      "gender": "Masculino",
      "entries": [
        {
          "position": 1,
          "archer_id": "uuid",
          "name": "Juan Pérez",
          "total_points": 320,
          "x_count": 5,
          "ten_count": 12
        }
      ]
    }
  ]
}
```

**Tournament stats payload:**
```json
{
  "tournament_id": "uuid",
  "archers": [
    {
      "archer_id": "uuid",
      "name": "Juan Pérez",
      "avg_points_per_arrow": 8.75,
      "top_zone_percentage": 42.50,
      "rounds": [
        {"round_number": 1, "total_points": 280},
        {"round_number": 2, "total_points": 295}
      ]
    }
  ]
}
```

**Archer trend payload:**
```json
[
  {"tournament_name": "Copa Primavera", "date": "2024-03-15", "avg_points_per_arrow": 8.20},
  {"tournament_name": "Copa Otoño",     "date": "2024-09-20", "avg_points_per_arrow": 8.75}
]
```

**Global ranking payload:**
```json
[
  {
    "position": 1,
    "archer_id": "uuid",
    "name": "Ana García",
    "total_points": 1850,
    "avg_points_per_arrow": 9.10,
    "tournaments_played": 3
  }
]
```

### Sesiones de arquero

Flask sessions firmadas (cookie `SESSION_SECRET`). Estructura:
```json
{
  "archer_id": "uuid",
  "archer_name": "Juan Pérez",
  "last_active": "2024-09-20T14:30:00"
}
```
La sesión expira si `last_active` supera 30 minutos respecto al momento de cada request.


---

## Correctness Properties

*Una propiedad es una característica o comportamiento que debe cumplirse en todas las ejecuciones válidas del sistema — esencialmente, un enunciado formal sobre lo que el sistema debe hacer. Las propiedades sirven como puente entre las especificaciones legibles por humanos y las garantías de corrección verificables automáticamente.*

---

### Property 1: Singleton de conexión

*Para cualquier* número N de invocaciones a `get_connection()` durante el ciclo de vida de la aplicación, todas las llamadas deben retornar exactamente la misma instancia de conexión (identidad de objeto).

**Validates: Requirements 1.5**

---

### Property 2: Creación de torneo con entradas válidas

*Para cualquier* nombre de torneo de entre 1 y 150 caracteres y cualquier fecha en formato `YYYY-MM-DD`, `create_tournament()` debe persistir el torneo con `status = 'created'` y un `id` que sea un UUID v4 válido.

**Validates: Requirements 2.1**

---

### Property 3: Rechazo de torneos con entradas inválidas

*Para cualquier* nombre vacío, nombre de más de 150 caracteres, o fecha con formato distinto de `YYYY-MM-DD`, `create_tournament()` debe retornar un error que identifica el campo inválido y no debe crear ningún registro en la tabla `tournaments`.

**Validates: Requirements 2.2**

---

### Property 4: Persistencia de categorías

*Para cualquier* combinación válida de `(tournament_id, bow_type, distance, gender)`, `create_category()` debe persistir la categoría con todos los atributos correctos y recuperable por su `id`.

**Validates: Requirements 2.3**

---

### Property 5: Unicidad de categorías

*Para cualquier* categoría ya existente en la base de datos, intentar crear una segunda categoría con la misma combinación `(tournament_id, bow_type, distance, gender)` debe retornar un error sin incrementar el conteo de categorías en la DB.

**Validates: Requirements 2.5**

---

### Property 6: Transiciones de estado inválidas del torneo

*Para cualquier* par de estados `(from_status, to_status)` que constituya una transición inválida (`finished → created`, `finished → active`, `active → created`), `change_tournament_status()` debe retornar un error y dejar el campo `status` del torneo sin modificar.

**Validates: Requirements 2.8**

---

### Property 7: Ordenamiento del listado de torneos

*Para cualquier* conjunto de N torneos con distintos `created_at`, `list_tournaments()` debe retornar exactamente N torneos ordenados de forma descendente por `created_at`.

**Validates: Requirements 2.9**

---

### Property 8: Creación de arquero con entradas válidas

*Para cualquier* nombre de arquero de entre 1 y 100 caracteres y cualquier PIN de exactamente 4 dígitos numéricos, `create_archer()` debe persistir el arquero con un `id` UUID v4 válido recuperable desde la base de datos.

**Validates: Requirements 3.1**

---

### Property 9: Rechazo de PIN con formato inválido

*Para cualquier* valor de PIN que no sea exactamente 4 dígitos numéricos (longitud incorrecta, caracteres no numéricos, cadena vacía), `create_archer()` debe retornar un error y no crear ningún registro en la tabla `archers`.

**Validates: Requirements 3.2**

---

### Property 10: Unicidad de PIN

*Para cualquier* PIN ya registrado en la base de datos, intentar crear un nuevo arquero con ese mismo PIN debe retornar un error sin incrementar el conteo de arqueros en la DB.

**Validates: Requirements 3.4**

---

### Property 11: Inscripción válida de arquero en torneo

*Para cualquier* arquero existente y cualquier torneo con estado `created` o `active` con una categoría válida perteneciente a ese torneo, `enroll_archer()` debe crear exactamente un registro en `registrations` con los tres IDs correctos.

**Validates: Requirements 3.5**

---

### Property 12: Unicidad de inscripción

*Para cualquier* inscripción ya existente en la base de datos, intentar inscribir el mismo arquero en la misma categoría del mismo torneo debe retornar un error sin incrementar el conteo de registros en `registrations`.

**Validates: Requirements 3.8**

---

### Property 13: Ordenamiento alfabético del listado de arqueros

*Para cualquier* conjunto de N arqueros con nombres distintos, `list_archers()` debe retornar exactamente N arqueros ordenados alfabéticamente de forma ascendente por nombre.

**Validates: Requirements 3.9**

---

### Property 14: Autenticación con PIN válido

*Para cualquier* arquero registrado en la base de datos, ingresar su PIN a través de `authenticate_pin()` debe producir una sesión que contiene el `archer_id` y el `name` correctos del arquero.

**Validates: Requirements 4.1**

---

### Property 15: Rechazo de PIN no registrado

*Para cualquier* PIN de 4 dígitos que no corresponda a ningún arquero en la base de datos, `authenticate_pin()` debe retornar un error genérico sin revelar información sobre otros arqueros ni crear ninguna sesión.

**Validates: Requirements 4.2**

---

### Property 16: Validez de sesión por tiempo de actividad

*Para cualquier* timestamp de última actividad `last_active`, la sesión debe considerarse válida si y solo si `(now - last_active) ≤ 30 minutos`. Para tiempos superiores a 30 minutos, la sesión debe ser rechazada y requerir reautenticación.

**Validates: Requirements 4.4**

---

### Property 17: Rechazo de PIN con formato inválido en autenticación

*Para cualquier* valor ingresado en el campo de PIN que no tenga exactamente 4 dígitos numéricos, `authenticate_pin()` debe rechazarlo sin realizar consulta alguna a la base de datos.

**Validates: Requirements 4.6**

---

### Property 18: Corrección del mapeo flecha → puntos

*Para cualquier* valor de `arrow_val` en el conjunto `{X, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, M}` enviado por un arquero autenticado en un torneo activo, `save_arrow()` debe persistir el registro en `scores` con `arrow_val` exactamente igual al valor enviado y `points` igual al valor numérico correcto según el mapeo definido (`X`→10, `10`→10, `9`→9, …, `1`→1, `M`→0).

**Validates: Requirements 5.2**

---

### Property 19: Invariante de puntos acumulados

*Para cualquier* secuencia de N flechas registradas por un arquero en un torneo, `get_accumulated_points()` debe retornar exactamente la suma aritmética de los valores `points` de todas esas flechas.

**Validates: Requirements 5.7**

---

### Property 20: Ordenamiento y estructura del leaderboard

*Para cualquier* torneo con M categorías y arqueros con puntajes registrados, `compute_leaderboard()` debe: (a) agrupar a los arqueros por categoría, (b) ordenarlos dentro de cada categoría por `total_points` DESC, luego `x_count` DESC, luego `ten_count` DESC, y (c) incluir para cada entrada los campos `position`, `name`, `total_points`, `x_count` y `ten_count`.

**Validates: Requirements 6.3, 6.4**

---

### Property 21: Estado inicial completo en conexión SSE

*Para cualquier* torneo con puntajes registrados, cuando un cliente se conecta al endpoint SSE, el primer evento recibido debe contener el estado completo actual del leaderboard (todos los arqueros de todas las categorías con sus métricas correctas).

**Validates: Requirements 6.6**

---

### Property 22: Promedio de puntos por flecha en estadísticas de torneo

*Para cualquier* arquero con K flechas registradas en un torneo, `tournament_stats()` debe retornar `avg_points_per_arrow = round(sum(points) / K, 2)` para ese arquero.

**Validates: Requirements 7.1**

---

### Property 23: Porcentaje de zona alta en estadísticas de torneo

*Para cualquier* arquero con K flechas registradas en un torneo, `tournament_stats()` debe retornar `top_zone_percentage = round(count(arrow_val in {X, 10}) / K * 100, 2)` para ese arquero.

**Validates: Requirements 7.2**

---

### Property 24: Ordenamiento de rondas en estadísticas de torneo

*Para cualquier* arquero con datos en múltiples rondas de un torneo, `tournament_stats()` debe retornar la serie de rondas ordenada de forma ascendente por `round_number`.

**Validates: Requirements 7.3**

---

### Property 25: Aislamiento de datos por arquero en estadísticas

*Para cualquier* arquero autenticado que solicita estadísticas de un torneo, `tournament_stats(tournament_id, archer_id=X)` debe retornar únicamente las métricas del arquero X, sin incluir datos de otros arqueros registrados en ese torneo.

**Validates: Requirements 7.5, 7.7**

---

### Property 26: Tendencia histórica — cálculo, formato y orden

*Para cualquier* arquero con participación en torneos con `status = 'finished'`, `archer_trend()` debe retornar un arreglo de objetos donde: (a) cada objeto contiene los campos `tournament_name`, `date` y `avg_points_per_arrow`, (b) `avg_points_per_arrow` es calculado correctamente como `round(sum(points) / count(arrows), 2)` para ese torneo (o 0.00 si no hay flechas), y (c) el arreglo está ordenado de forma ascendente por `date`.

**Validates: Requirements 8.1, 8.2**

---

### Property 27: Corrección del ranking global

*Para cualquier* conjunto de arqueros con puntajes en torneos `finished`, `global_ranking()` debe retornar para cada arquero: `total_points` igual a la suma de todos sus `points` en torneos `finished`, `avg_points_per_arrow` igual a `round(total_points / total_arrows, 2)`, y `tournaments_played` igual al conteo de torneos `finished` distintos en los que participó.

**Validates: Requirements 9.1**

---

### Property 28: Ordenamiento del ranking global

*Para cualquier* conjunto de arqueros en el ranking, `global_ranking()` debe ordenarlos por `total_points` DESC y, en caso de empate, por `name` ASC.

**Validates: Requirements 9.2**

---

### Property 29: Filtro de torneos finished en el ranking global

*Para cualquier* arquero con puntajes en torneos con estado `created` o `active`, esos puntajes NO deben sumarse a su `total_points` en `global_ranking()`. Solo los puntajes de torneos `finished` deben contribuir al ranking.

**Validates: Requirements 9.3**

---

## Error Handling

### Estrategia general

Todos los errores se retornan como JSON con la estructura:
```json
{"error": "descripción legible del problema", "field": "campo_afectado (opcional)"}
```

Los errores de validación incluyen el campo `field` para facilitar el destacado en la UI.

### Errores por módulo

| Escenario | Código HTTP | Mensaje |
|-----------|-------------|---------|
| Torneo no encontrado | 404 | "Torneo no encontrado" |
| Categoría duplicada | 409 | "La categoría ya existe para este torneo" |
| Transición de estado inválida | 422 | "Transición de estado no permitida: {from} → {to}" |
| PIN ya en uso | 409 | "El PIN ya está en uso" |
| PIN incorrecto (login) | 401 | "PIN incorrecto" |
| Arquero bloqueado por intentos | 429 | "Demasiados intentos. Espere {N} minutos." |
| No hay torneos activos | 403 | "No hay torneos activos para este arquero" |
| Torneo no activo (score) | 403 | "El torneo no está activo" |
| DB no disponible | 503 | "Servicio no disponible temporalmente" |
| Conexión Turso timeout | — | Log interno + exit(1) |

### Manejo de fallo en persistencia de flecha

Cuando `save_arrow()` falla:
1. El `end_number` no se incrementa en la sesión del request.
2. Se retorna `{"error": "No se pudo guardar la flecha. Intente nuevamente."}` con HTTP 500.
3. La UI muestra el mensaje de error y mantiene el estado visual de la tanda sin avanzar.

### Degradación de Alpine.js

Si Alpine.js no carga desde CDN:
- Los formularios de carga de puntuaciones funcionan en modo `<form>` estático con POST tradicional.
- Los botones del teclado táctil envían el valor mediante `<button type="submit" name="arrow_val" value="X">`.
- Las actualizaciones de totales se muestran al recargar la vista tras cada flecha.

---

## Testing Strategy

### Herramienta de property-based testing

Se usa **Hypothesis** (Python) como biblioteca de PBT. Cada test de propiedad ejecuta un mínimo de **100 iteraciones**.

Etiqueta de referencia para cada test:
```
# Feature: kiro-archery, Property {N}: {texto de la propiedad}
```

### Tests unitarios y de propiedad

| Tipo | Foco | Herramienta |
|------|------|-------------|
| Unit / Example | Escenarios concretos, casos borde, transiciones de estado | `pytest` |
| Property-based | Propiedades universales (Propiedades 1–29) | `pytest` + `hypothesis` |
| Integration | SSE timing, latencia de UI, DB real | `pytest` + `requests` / `selenium` |
| Smoke | Disponibilidad de endpoint, rendering de CDN | `pytest` + `requests` |

### Organización de los tests

```
tests/
├── unit/
│   ├── test_db.py              # Propiedad 1, ejemplos 1.2, 1.3
│   ├── test_admin.py           # Propiedades 2–13
│   ├── test_archer.py          # Propiedades 14–19
│   ├── test_leaderboard.py     # Propiedades 20–21
│   └── test_stats.py           # Propiedades 22–29
├── integration/
│   ├── test_sse.py             # Req 6.2, 6.5, 6.7
│   └── test_ui_timing.py       # Req 10.3
└── smoke/
    └── test_endpoints.py       # Req 6.1, 10.1, 10.2, 10.4
```

### Cobertura de tests por requisito

| Requerimiento | Propiedades PBT | Tests de ejemplo | Tests de borde |
|---|---|---|---|
| 1 — DB Connection | P1 | 1.2, 1.3 | 1.4 |
| 2 — Tournament Mgmt | P2, P3, P4, P5, P6, P7 | 2.6, 2.7 | 2.4 |
| 3 — Archer Registration | P8, P9, P10, P11, P12, P13 | — | 3.3, 3.6, 3.7 |
| 4 — PIN Auth | P14, P15, P16, P17 | 4.5 | 4.3, 4.7 |
| 5 — Score Entry | P18, P19 | 5.6 | 5.3, 5.4, 5.5 |
| 6 — Live Leaderboard | P20, P21 | — | Integration: 6.2, 6.5, 6.7 |
| 7 — Tournament Stats | P22, P23, P24, P25 | — | 7.4, 7.6 |
| 8 — Archer Trend | P26 | — | 8.3, 8.4 |
| 9 — Global Ranking | P27, P28, P29 | 9.5 | 9.4, 9.6 |
| 10 — Mobile UI | — | 10.5 | Smoke: 10.1, 10.2, 10.4 |

### Ejemplo de test con Hypothesis (Propiedad 18)

```python
from hypothesis import given, settings
import hypothesis.strategies as st

# Feature: kiro-archery, Property 18: Corrección del mapeo flecha → puntos
@given(
    arrow_val=st.sampled_from(["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"])
)
@settings(max_examples=100)
def test_arrow_points_mapping(arrow_val, test_db, active_tournament, authenticated_archer):
    expected_points = {"X": 10, "10": 10, "9": 9, "8": 8, "7": 7,
                       "6": 6, "5": 5, "4": 4, "3": 3, "2": 2, "1": 1, "M": 0}
    result = save_arrow(
        archer_id=authenticated_archer["id"],
        tournament_id=active_tournament["id"],
        round_number=1, end_number=1,
        arrow_val=arrow_val
    )
    assert result["arrow_val"] == arrow_val
    assert result["points"] == expected_points[arrow_val]
```

### Uso de fixtures y mocks

- La base de datos de tests usa SQLite en memoria (`:memory:`), lo que hace los tests de propiedad rápidos y sin efectos secundarios.
- El `Leaderboard_Module` expone una interfaz con cola interna que puede ser reemplazada por un mock en tests unitarios.
- Los tests de integración SSE usan una instancia Flask real levantada en un thread de test con `threading.Thread`.
