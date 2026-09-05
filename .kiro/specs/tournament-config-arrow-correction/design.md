# Design Document: Tournament Config & Arrow Correction

## Overview

Este documento describe el diseño técnico para dos nuevas funcionalidades del sistema Archer App:

1. **Configuración de rondas y flechas por torneo** — el administrador puede definir cuántas rondas y cuántas flechas por tanda tiene un torneo, eliminando los valores hardcodeados `ARROWS_PER_END = 6` y `ENDS_PER_ROUND = 10` del módulo `archer.py`.

2. **Corrección de flechas** — el arquero puede corregir una flecha de la tanda activa; el administrador puede corregir cualquier flecha en cualquier ronda. Ambas correcciones actualizan el mapeo `arrow_val → points` y disparan una actualización del leaderboard en vivo.

La feature es aditiva y backward-compatible: los torneos existentes conservan su comportamiento actual gracias a los defaults aplicados durante la migración de esquema.

---

## Architecture

El diseño sigue la arquitectura Flask Blueprint ya establecida en el proyecto. No se introduce ninguna capa adicional; los cambios se distribuyen en las capas existentes:

```
┌─────────────────────────────────────────────────────────┐
│  Templates (Jinja2 + Tailwind CSS + Alpine.js)          │
│  admin/tournaments.html  ·  archer/score.html           │
│  admin/enrolled_archers.html                            │
└───────────────┬─────────────────────────┬───────────────┘
                │ HTTP (form / fetch)      │
┌───────────────▼──────────┐  ┌───────────▼───────────────┐
│  admin_routes.py         │  │  archer_routes.py          │
│  Blueprint /admin        │  │  Blueprint /archer         │
└───────────────┬──────────┘  └───────────┬───────────────┘
                │                         │
┌───────────────▼──────────┐  ┌───────────▼───────────────┐
│  modules/admin.py        │  │  modules/archer.py         │
│  create_tournament()     │  │  save_arrow()              │
│  list_tournaments()      │  │  correct_arrow_archer()    │
└───────────────┬──────────┘  │  get_end_summary()         │
                │             │  get_accumulated_points()  │
                │             └───────────┬───────────────┘
                │                         │
┌───────────────▼─────────────────────────▼───────────────┐
│  db.py — get_connection() / init_db()                   │
│  Turso (libsql-experimental) · SQLite fallback          │
└─────────────────────────────────────────────────────────┘
```

### Flujo de corrección de flechas

```
Arquero                   archer_routes         archer.py         leaderboard.py
   │                           │                    │                   │
   │─ POST /archer/score/correct ─►                 │                   │
   │                           │─ correct_arrow_archer() ─►            │
   │                           │                    │ validate ownership│
   │                           │                    │ validate active_end│
   │                           │                    │ validate arrow_val │
   │                           │                    │── UPDATE scores ──►│
   │                           │                    │◄── updated_record ─│
   │                           │                    │── broadcast_update()─►
   │◄─ redirect (PRG) ─────────│◄── result ─────────│                   │

Admin                     admin_routes          admin.py          leaderboard.py
   │                           │                    │                   │
   │─ POST /admin/scores/correct ─►                 │                   │
   │                           │─ correct_arrow_admin() ─►             │
   │                           │                    │ validate score_id │
   │                           │                    │ validate arrow_val │
   │                           │                    │── UPDATE scores ──►│
   │                           │                    │── broadcast_update()─►
   │◄─ redirect (PRG) ─────────│◄── result ─────────│                   │
```

---

## Components and Interfaces

### 1. DB Module — `archer/db.py`

**Cambio:** `init_db()` debe añadir las columnas `rounds` y `arrows_per_end` a la tabla `tournaments`, tanto en creaciones nuevas como en migraciones de esquemas existentes.

```python
# Estrategia de migración en init_db():
# 1. CREATE TABLE IF NOT EXISTS con las nuevas columnas
# 2. ALTER TABLE ... ADD COLUMN con IF NOT EXISTS (o try/except en SQLite)
```

Las dos sentencias de migración segura a añadir al final de `init_db()`:

```python
_MIGRATIONS = [
    "ALTER TABLE tournaments ADD COLUMN rounds INTEGER NOT NULL DEFAULT 10",
    "ALTER TABLE tournaments ADD COLUMN arrows_per_end INTEGER NOT NULL DEFAULT 6",
]
# Ejecutar cada una en try/except OperationalError para tolerar que la
# columna ya exista (SQLite no soporta IF NOT EXISTS en ALTER TABLE).
```

### 2. Admin Module — `archer/modules/admin.py`

**Funciones modificadas:**

#### `create_tournament(name, date, rounds=10, arrows_per_end=6)`

Firma actualizada para recibir los nuevos parámetros con defaults. Validaciones adicionales:

- `rounds` debe ser entero en `[1, 20]` → retorna `{"error": "...", "field": "rounds"}`.
- `arrows_per_end` debe ser entero en `[1, 12]` → retorna `{"error": "...", "field": "arrows_per_end"}`.

```python
def create_tournament(name: str, date: str, rounds: int = 10, arrows_per_end: int = 6) -> dict:
    # Validaciones existentes (name, date) ...
    # Nuevas validaciones:
    try:
        rounds = int(rounds)
    except (TypeError, ValueError):
        return {"error": "El número de rondas debe ser un entero.", "field": "rounds"}
    if not (1 <= rounds <= 20):
        return {"error": "Las rondas deben estar entre 1 y 20.", "field": "rounds"}

    try:
        arrows_per_end = int(arrows_per_end)
    except (TypeError, ValueError):
        return {"error": "Las flechas por tanda deben ser un entero.", "field": "arrows_per_end"}
    if not (1 <= arrows_per_end <= 12):
        return {"error": "Las flechas por tanda deben estar entre 1 y 12.", "field": "arrows_per_end"}

    # INSERT incluye rounds y arrows_per_end
    conn.execute(
        "INSERT INTO tournaments (id, name, date, status, rounds, arrows_per_end) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tournament_id, name, date, "created", rounds, arrows_per_end),
    )
```

**Función nueva:**

#### `correct_arrow_admin(score_id, arrow_val) -> dict`

Corrección de flechas sin restricción de ronda (solo admin):

```python
def correct_arrow_admin(score_id: str, arrow_val: str) -> dict:
    """
    Actualiza arrow_val y points de un score por score_id.
    - score_id no existe → {"error": "...", "status_code": 404}
    - arrow_val inválido → {"error": "...", "field": "arrow_val"}
    - Éxito → dict del score actualizado + llama a broadcast_update()
    """
```

### 3. Archer Module — `archer/modules/archer.py`

**Constantes a conservar (solo para retrocompatibilidad en tests):**

Las constantes `ARROWS_PER_END` y `ENDS_PER_ROUND` se mantienen en el módulo pero **dejan de usarse en la lógica de progresión de sesión**. La ruta `archer_routes.py` leerá los valores directamente del dict del torneo.

**Función modificada:**

#### `get_active_tournament(archer_id)` — sin cambios de firma, pero el SELECT ahora incluye `rounds` y `arrows_per_end`:

```python
cursor = conn.execute(
    """
    SELECT t.id, t.name, t.date, t.status, t.rounds, t.arrows_per_end, t.created_at
    FROM registrations r
    JOIN tournaments t ON t.id = r.tournament_id
    WHERE r.archer_id = ? AND t.status = 'active'
    LIMIT 1
    """,
    (archer_id,),
)
```

**Función nueva:**

#### `correct_arrow_archer(score_id, arrow_val, archer_id, tournament_id, current_round, current_end) -> dict`

Corrección de flechas restringida a la tanda activa:

```python
def correct_arrow_archer(
    score_id: str,
    arrow_val: str,
    archer_id: str,
    tournament_id: str,
    current_round: int,
    current_end: int,
) -> dict:
    """
    Reglas de negocio:
    1. arrow_val inválido → {"error": "...", "field": "arrow_val"}
    2. score no existe o no pertenece a archer_id/tournament_id → {"error": "...", "status_code": 403}
    3. score pertenece a ronda/tanda confirmada → {"error": "...", "status_code": 403}
    4. Éxito → UPDATE scores, dict actualizado + broadcast_update()
    """
```

La determinación de **tanda activa vs. confirmada** sigue la definición del glosario:
- Una flecha está en la tanda activa si `score.round_number == current_round AND score.end_number == current_end`.
- Una flecha pertenece a una ronda confirmada si `score.round_number < current_round` o (`score.round_number == current_round AND score.end_number < current_end`).

### 4. Admin Routes — `archer/routes/admin_routes.py`

**Rutas modificadas:**

- `POST /admin/tournaments` → leer `rounds` y `arrows_per_end` del form y pasarlos a `create_tournament()`.
- `GET /admin/tournaments` → `list_tournaments()` ya retorna las nuevas columnas; el template las renderiza.

**Ruta nueva:**

```
POST /admin/scores/correct
```

Cuerpo del form: `score_id`, `arrow_val`, `redirect_to` (URL de retorno, e.g. enrolled_archers).

```python
@admin_bp.route("/scores/correct", methods=["POST"])
@require_admin
def correct_score():
    score_id  = request.form.get("score_id", "").strip()
    arrow_val = request.form.get("arrow_val", "").strip()
    redirect_to = request.form.get("redirect_to", url_for("admin.tournaments"))

    result = correct_arrow_admin(score_id, arrow_val)
    if "error" in result:
        # Re-renderizar con error
        ...
    return redirect(redirect_to)
```

### 5. Archer Routes — `archer/routes/archer_routes.py`

**`score_post()` modificada:**

Reemplaza el uso de las constantes `ARROWS_PER_END` / `ENDS_PER_ROUND` por los valores del torneo:

```python
arrows_per_end  = tournament["arrows_per_end"]
ends_per_round  = tournament["rounds"]  # "rounds" en DB = ends_per_round semánticamente

arrow_count = get_end_arrow_count(archer_id, tournament["id"], round_number, end_number)
if arrow_count >= arrows_per_end:
    if end_number >= ends_per_round:
        session["end_number"] = 1
        session["round_number"] = round_number + 1
    else:
        session["end_number"] = end_number + 1
```

> **Nota de nomenclatura:** La columna en la tabla se llama `rounds` (número de rondas del torneo). El nombre del parámetro de sesión `end_number` se refiere a la tanda dentro de una ronda. `rounds` como límite de tandas por ronda equivale conceptualmente a `ENDS_PER_ROUND`. Esto es una decisión de diseño existente que se preserva para minimizar cambios.

**Ruta nueva:**

```
POST /archer/score/correct
```

```python
@archer_bp.route("/score/correct", methods=["POST"])
@require_session
def correct_arrow():
    score_id  = request.form.get("score_id", "").strip()
    arrow_val = request.form.get("arrow_val", "").strip()
    archer_id = session["archer_id"]
    round_number = session.get("round_number", 1)
    end_number   = session.get("end_number", 1)

    tournament = get_active_tournament(archer_id)
    if tournament is None:
        return _render_score(error="No hay torneo activo."), 403

    result = correct_arrow_archer(
        score_id, arrow_val, archer_id,
        tournament["id"], round_number, end_number,
    )
    if "error" in result:
        status = result.get("status_code", 400)
        return _render_score(error=result["error"]), status

    session["last_active"] = datetime.now().isoformat()
    return redirect(url_for("archer.score"))
```

---

## Data Models

### Cambio de esquema: tabla `tournaments`

Se añaden dos columnas con `ALTER TABLE ... ADD COLUMN`:

```sql
ALTER TABLE tournaments ADD COLUMN rounds         INTEGER NOT NULL DEFAULT 10;
ALTER TABLE tournaments ADD COLUMN arrows_per_end INTEGER NOT NULL DEFAULT 6;
```

**Esquema completo resultante:**

```sql
CREATE TABLE IF NOT EXISTS tournaments (
    id            TEXT    PRIMARY KEY,
    name          TEXT    NOT NULL,
    date          TEXT    NOT NULL,
    status        TEXT    CHECK(status IN ('created', 'active', 'finished'))
                          DEFAULT 'created',
    rounds        INTEGER NOT NULL DEFAULT 10,
    arrows_per_end INTEGER NOT NULL DEFAULT 6,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Restricciones de negocio (aplicadas en capa de aplicación):**

| Campo          | Tipo    | Rango válido | Default |
|----------------|---------|-------------|---------|
| `rounds`       | INTEGER | [1, 20]     | 10      |
| `arrows_per_end` | INTEGER | [1, 12]   | 6       |

La tabla `scores` **no cambia**. La corrección de flechas opera con UPDATE sobre registros existentes:

```sql
UPDATE scores
SET arrow_val = ?, points = ?
WHERE id = ?
```

### Dict de torneo (después del cambio)

```python
{
    "id": "uuid-v4",
    "name": "Copa Primavera 2025",
    "date": "2025-04-15",
    "status": "active",
    "rounds": 10,         # ← nuevo
    "arrows_per_end": 6,  # ← nuevo
    "created_at": "2025-01-01T10:00:00"
}
```

### Dict de resultado de corrección

```python
# Éxito
{
    "id": "score-uuid",
    "tournament_id": "tournament-uuid",
    "archer_id": "archer-uuid",
    "round_number": 2,
    "end_number": 3,
    "arrow_val": "9",
    "points": 9,
}

# Error
{
    "error": "Descripción del error",
    "field": "arrow_val",  # opcional
    "status_code": 400     # opcional, default 400
}
```

---

## Correctness Properties

*Una propiedad es una característica o comportamiento que debe mantenerse verdadero en todas las ejecuciones válidas de un sistema — esencialmente, una declaración formal sobre lo que el sistema debe hacer. Las propiedades sirven como puente entre especificaciones legibles por humanos y garantías de corrección verificables por máquina.*

### Property 1: Persistencia de configuración de torneo (round-trip)

*Para cualquier* valor de `rounds` en `[1, 20]` y `arrows_per_end` en `[1, 12]`, al crear un torneo con esos valores y recuperarlo de la base de datos, los campos `rounds` y `arrows_per_end` del registro recuperado deben ser idénticos a los valores proporcionados en la creación.

**Validates: Requirements 1.1**

---

### Property 2: Rechazo de rounds fuera del rango válido

*Para cualquier* valor entero de `rounds` fuera del rango `[1, 20]` (incluyendo 0, negativos e integers > 20), la función `create_tournament()` debe rechazar la solicitud y retornar un error con `field='rounds'`, sin crear ningún registro en la base de datos.

**Validates: Requirements 1.3**

---

### Property 3: Rechazo de arrows_per_end fuera del rango válido

*Para cualquier* valor entero de `arrows_per_end` fuera del rango `[1, 12]` (incluyendo 0, negativos e integers > 12), la función `create_tournament()` debe rechazar la solicitud y retornar un error con `field='arrows_per_end'`, sin crear ningún registro en la base de datos.

**Validates: Requirements 1.4**

---

### Property 4: Progresión de tanda basada en configuración del torneo

*Para cualquier* valor de `arrows_per_end` en `[1, 12]`, al guardar exactamente `arrows_per_end` flechas en la tanda actual, el sistema debe avanzar `end_number` al siguiente valor. La progresión debe ocurrir precisamente al llegar al límite configurado, no al valor hardcodeado anterior de 6.

**Validates: Requirements 2.1, 2.4**

---

### Property 5: Rollover de ronda basado en configuración del torneo

*Para cualquier* valor de `rounds` (equivalente a `ends_per_round`) en `[1, 20]`, al completar la última tanda de una ronda (`end_number == rounds`), el sistema debe incrementar `round_number` en 1 y resetear `end_number` a 1.

**Validates: Requirements 2.2**

---

### Property 6: Corrección de flecha en tanda activa — invariante de mapeo

*Para cualquier* flecha en la tanda activa y cualquier `arrow_val` válido en `["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"]`, al aplicar una corrección el campo `points` del registro actualizado debe ser exactamente el valor definido por el mapping `X→10, 10→10, 9→9, 8→8, 7→7, 6→6, 5→5, 4→4, 3→3, 2→2, 1→1, M→0`.

**Validates: Requirements 3.1, 6.1**

---

### Property 7: Corrección de flecha — round-trip de doble corrección

*Para cualquier* flecha con `arrow_val` original `v1`, al corregirla a un valor `v2 ≠ v1` y luego volver a corregirla al valor original `v1`, el registro resultante debe ser idéntico en `arrow_val` y `points` al estado previo a la primera corrección.

**Validates: Requirements 6.2**

---

### Property 8: Rechazo de corrección de flecha con arrow_val inválido (arquero y admin)

*Para cualquier* string que no pertenezca al conjunto `{"X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"}`, tanto `correct_arrow_archer()` como `correct_arrow_admin()` deben rechazar la solicitud retornando un error con `field='arrow_val'`, sin modificar ningún registro.

**Validates: Requirements 3.3, 4.3**

---

### Property 9: Rechazo de corrección de ronda confirmada por el arquero

*Para cualquier* flecha que pertenezca a una ronda confirmada (es decir, `score.round_number < current_round`, o `score.round_number == current_round AND score.end_number < current_end`), la función `correct_arrow_archer()` debe rechazar la solicitud retornando un error con HTTP 403, sin modificar el registro.

**Validates: Requirements 3.2**

---

### Property 10: Rechazo de corrección de flecha ajena al arquero (HTTP 403)

*Para cualquier* `score_id` que no pertenezca al `archer_id` y `tournament_id` de la sesión activa, la función `correct_arrow_archer()` debe rechazar la solicitud retornando un error con HTTP 403, sin modificar ningún registro.

**Validates: Requirements 3.4**

---

### Property 11: Invariante de puntos acumulados tras correcciones

*Para cualquier* secuencia de flechas guardadas y correcciones aplicadas, `get_accumulated_points(archer_id, tournament_id)` debe retornar exactamente la suma aritmética de los valores actuales de `points` de todos los registros `scores` del arquero en ese torneo: `sum(s.points for s in scores where archer_id and tournament_id)`.

**Validates: Requirements 6.3**

---

### Property 12: Corrección administrativa — sin restricción de ronda

*Para cualquier* `score_id` existente en la tabla `scores` y cualquier `arrow_val` válido, `correct_arrow_admin()` debe actualizar el registro correctamente independientemente del `round_number` o `end_number` al que pertenezca.

**Validates: Requirements 4.1**

---

### Property 13: Retrocompatibilidad de migración — defaults en registros existentes

*Para cualquier* cantidad de registros de torneos existentes en la tabla antes de ejecutar la migración (es decir, sin las columnas `rounds` y `arrows_per_end`), después de ejecutar `init_db()` todos los registros deben tener `rounds = 10` y `arrows_per_end = 6`, preservando todos los demás campos sin modificación.

**Validates: Requirements 5.3**

---

## Error Handling

### Códigos HTTP por caso de uso

| Situación | Código HTTP |
|-----------|------------|
| Validación de campo (rounds, arrows_per_end, arrow_val inválido) | 400 |
| Corrección de flecha ajena al arquero | 403 |
| Intento de corregir ronda confirmada como arquero | 403 |
| score_id no encontrado (admin) | 404 |
| Transición de estado inválida | 422 |
| Error interno de DB | 500 |

### Respuesta de error estándar

Todos los errores retornan un dict consistente con el patrón ya establecido en el proyecto:

```python
{
    "error": "Descripción legible del error.",
    "field": "nombre_del_campo",  # presente solo cuando aplica a un campo específico
    "status_code": 400             # usado internamente para determinar el HTTP status
}
```

### Manejo de errores en rutas

Las rutas siguen el patrón existente: si la función de módulo retorna `"error"` en el dict, se re-renderiza el template con el mensaje de error. En operaciones AJAX (fetch), el cliente recarga la página al recibir respuesta no-ok.

### Consideraciones de concurrencia

La corrección de flechas es una operación atómica de `UPDATE` sobre un `score_id` único. SQLite/Turso garantizan atomicidad a nivel de sentencia. No se requiere bloqueo adicional ya que el escenario de escritura concurrente sobre el mismo `score_id` es extremadamente improbable en el contexto de uso (un arquero a la vez).

---

## Testing Strategy

### Herramienta de PBT

Se utiliza **Hypothesis** (ya incluido en `requirements.txt`) con el decorador `@settings(max_examples=100)` como mínimo. Las bases de datos de test usan SQLite en memoria (`:memory:`) para velocidad y aislamiento.

Tag format: `# Feature: tournament-config-arrow-correction, Property {N}: {texto}`

### Unit tests (ejemplo-based)

Ubicación: `tests/unit/test_tournament_config.py`, `tests/unit/test_arrow_correction.py`

- Crear torneo sin `rounds`/`arrows_per_end` → defaults 10 y 6.
- GET `/admin/tournaments` renderiza inputs `rounds` y `arrows_per_end` con valores default.
- Corrección de flecha con `score_id` inexistente → HTTP 404 (admin).
- `broadcast_update()` llamado tras corrección exitosa (arquero y admin).
- GET `/archer/score` con tanda activa renderiza botones de corrección por flecha.
- GET `/admin/tournaments/<id>/archers` renderiza controles de corrección de flechas.
- Migración sobre BD existente sin las nuevas columnas conserva registros previos.

### Property tests

Ubicación: `tests/unit/test_tournament_config_props.py`, `tests/unit/test_arrow_correction_props.py`

Cada test de propiedad mapea a una de las propiedades de corrección definidas arriba:

```python
from hypothesis import given, settings
from hypothesis import strategies as st

# Feature: tournament-config-arrow-correction, Property 1: Persistencia de configuración de torneo
@given(
    rounds=st.integers(min_value=1, max_value=20),
    arrows_per_end=st.integers(min_value=1, max_value=12),
)
@settings(max_examples=100)
def test_tournament_config_persistence(app, rounds, arrows_per_end):
    with app.app_context():
        result = create_tournament("Test", "2025-01-01", rounds, arrows_per_end)
        assert "error" not in result
        assert result["rounds"] == rounds
        assert result["arrows_per_end"] == arrows_per_end

# Feature: tournament-config-arrow-correction, Property 6: Corrección de flecha — invariante de mapeo
@given(arrow_val=st.sampled_from(["X","10","9","8","7","6","5","4","3","2","1","M"]))
@settings(max_examples=100)
def test_arrow_correction_points_invariant(app, arrow_val):
    # Crear score, corregirlo, verificar points == ARROW_POINTS[arrow_val]
    ...
```

### Smoke tests

- `PRAGMA table_info(tournaments)` incluye columnas `rounds` y `arrows_per_end`.

### Integración

- Flujo completo: crear torneo con `arrows_per_end=3`, guardar 3 flechas → verificar avance de tanda.
- Flujo completo: corregir flecha como arquero en tanda activa → leaderboard actualizado.
- Flujo completo: corregir flecha como admin en ronda confirmada → leaderboard actualizado.
