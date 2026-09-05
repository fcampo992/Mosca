# Design Document — archer-app-fixes

## Bug Details

Este documento cubre seis bugs críticos identificados en KiroArchery (Flask + Turso/libSQL):

- **Bug 1:** `score_post()` en `archer_routes.py` nunca incrementa `session["end_number"]` ni `session["round_number"]` tras guardar cada flecha vía PRG. Todas las flechas se persisten bajo `end_number=1, round_number=1`.
- **Bug 2:** El blueprint `/admin` en `admin_routes.py` no tiene ningún decorador de autenticación, middleware, ni verificación de sesión. Cualquier usuario con la URL puede acceder al panel completo.
- **Bug 3:** No existe ninguna ruta, endpoint ni función en `admin_routes.py`/`admin.py` que permita eliminar o resetear datos de prueba. Solo es posible con acceso directo a la DB.
- **Bug 4:** En `admin/tournaments.html`, la tarjeta de cada torneo solo muestra "Categorías" y botones de estado. Faltan links directos al leaderboard en vivo, estadísticas del torneo y arqueros inscritos.
- **Bug 5:** `admin_routes.py` no tiene ninguna ruta DELETE/POST para eliminar torneos, y `admin.py` no expone `delete_tournament()`.
- **Bug 6:** `stats_routes.py` expone rutas de estadísticas que no tienen ningún link desde la sesión del arquero y no verifican que el solicitante tiene permisos para ver los datos.

## Hypothesized Root Cause

- **Bug 1:** El patrón PRG (Post-Redirect-Get) fue implementado para prevenir doble envío, pero la lógica de avance de tanda (incrementar `session["end_number"]`) nunca fue escrita. La sesión es inicializada correctamente en login con `end_number=1, round_number=1`, pero nunca actualizada en `score_post()`.
- **Bug 2:** El blueprint admin fue desarrollado únicamente con funcionalidad de gestión, asumiendo que la autenticación sería agregada posteriormente. No se implementó el `require_admin` decorator ni las rutas `/admin/login` y `/admin/logout`.
- **Bug 3:** No se consideró el flujo de desarrollo/testing que requiere reset de datos. Solo se previó la creación de entidades, no su eliminación.
- **Bug 4:** Las tarjetas de torneo fueron diseñadas para las operaciones CRUD básicas. Los accesos directos a vistas de solo lectura (leaderboard, stats, arqueros) fueron omitidos en la implementación inicial del template.
- **Bug 5:** Al igual que Bug 3, solo se implementó el ciclo de creación. La funcionalidad de eliminación de torneos no fue incluida.
- **Bug 6:** Las rutas de stats fueron implementadas como endpoints de solo consulta sin considerar la necesidad de enlazarlas desde el flujo del arquero ni protegerlas con verificación de identidad.

## Expected Behavior

- **Bug 1:** Después de registrar `ARROWS_PER_END` flechas en una tanda, `session["end_number"]` debe incrementar automáticamente. Al completar todas las tandas de una ronda, `session["round_number"]` debe incrementar y `session["end_number"]` resetearse a 1.
- **Bug 2:** Cualquier petición a una ruta `/admin/*` sin `session["admin_logged_in"]` debe resultar en HTTP 302 a `/admin/login`. El login valida credenciales desde variables de entorno.
- **Bug 3:** El admin puede eliminar arqueros que no tienen inscripciones en torneos `active` o `finished`. La operación se realiza desde el panel de administración sin necesidad de acceso directo a la DB.
- **Bug 4:** Las tarjetas de torneo muestran: link a arqueros inscritos (siempre), link al leaderboard en vivo (solo `active`), link a estadísticas (solo `finished`).
- **Bug 5:** El admin puede eliminar torneos en estado `created`. La eliminación es en cascada: categorías y registraciones asociadas también son eliminadas. Torneos `active` o `finished` no pueden eliminarse.
- **Bug 6:** Un arquero autenticado ve el link "Mis stats" en su pantalla de score. Las rutas de stats verifican que el solicitante es el propio arquero o un admin. Los stats de un arquero no son accesibles por otro arquero.

## Fix Implementation

Los fixes se detallan en las secciones de Components and Interfaces y Architecture a continuación.

## Overview

Este documento describe el diseño técnico para corregir seis bugs críticos en la aplicación KiroArchery (Flask + Turso/libSQL). Los bugs cubren áreas de progresión de sesión durante el registro de flechas, autenticación del panel administrativo, gestión del ciclo de vida de datos (eliminación y reset), mejoras de UX en la vista de torneos, y accesibilidad del portal de estadísticas personales del arquero.

El enfoque es quirúrgico: cada fix modifica solo los componentes que presentan el defecto sin tocar funcionalidades ya verificadas. Se preservan todos los comportamientos documentados en la sección "Unchanged Behavior" del `bugfix.md`.

---

## Architecture

La aplicación sigue una arquitectura en capas Flask con Blueprints:

```
┌─────────────────────────────────────────────────────┐
│                    Flask App                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │  /archer │ │  /admin  │ │  /stats  │ │  /lb   │ │
│  │ Blueprint│ │ Blueprint│ │ Blueprint│ │  BP    │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       │            │            │            │      │
│  ┌────▼─────┐ ┌────▼─────┐ ┌────▼──────────┐│      │
│  │archer.py │ │ admin.py │ │   stats.py    ││      │
│  │ (module) │ │ (module) │ │   (module)    ││      │
│  └────┬─────┘ └────┬─────┘ └────┬──────────┘│      │
│       └────────────┴────────────┘           │      │
│                    │                         │      │
│             ┌──────▼───────┐                 │      │
│             │    db.py     │                 │      │
│             │ (connection) │                 │      │
│             └──────┬───────┘                 │      │
└────────────────────┼─────────────────────────┘      
                     │
                 Turso / SQLite
```

### Cambios por bug

| Bug | Archivos modificados |
|-----|---------------------|
| Bug 1 — Avance de tanda | `archer_routes.py`, `archer.py` |
| Bug 2 — Admin sin auth | `admin_routes.py`, `config.py`, nuevo `admin/login.html` |
| Bug 3 — Reset de datos | `admin_routes.py`, `admin.py`, `admin/archers.html` |
| Bug 4 — UX torneos | `admin/tournaments.html` |
| Bug 5 — Eliminar torneo | `admin_routes.py`, `admin.py`, `admin/tournaments.html` |
| Bug 6 — Stats no accesibles | `stats_routes.py`, `archer/score.html`, `admin/archers.html` |

---

## Components and Interfaces

### Bug 1 — Avance de tanda (`archer_routes.py` + `archer.py`)

**Problema:** `score_post()` nunca incrementa `session["end_number"]` ni `session["round_number"]` tras guardar una flecha. Todas las flechas se acumulan bajo `end_number=1, round_number=1`.

**Fix:** Añadir lógica de avance de tanda justo antes del redirect PRG en `score_post()`.

Se necesita saber cuántas flechas forman una tanda (`ARROWS_PER_END`). El estándar FITA/World Archery usa 3 o 6 flechas por tanda dependiendo de la distancia. Se usará una constante configurable con valor por defecto de 6.

```python
# archer/modules/archer.py — constante y nueva función
ARROWS_PER_END = 6   # valor configurable por distancia (futuro)
ENDS_PER_ROUND = 10  # tandas por ronda (configurable)

def get_end_arrow_count(archer_id: str, tournament_id: str,
                        round_number: int, end_number: int) -> int:
    """Retorna el número de flechas registradas en la tanda actual."""
    conn = get_connection()
    cursor = conn.execute(
        """
        SELECT COUNT(*) AS cnt FROM scores
        WHERE archer_id = ? AND tournament_id = ?
          AND round_number = ? AND end_number = ?
        """,
        (archer_id, tournament_id, round_number, end_number),
    )
    row = cursor.fetchone()
    return int(row["cnt"]) if row else 0
```

**Lógica de avance en `score_post()`:**

```python
# Después de guardar la flecha exitosamente:
arrow_count = get_end_arrow_count(
    archer_id, tournament["id"], round_number, end_number
)
if arrow_count >= ARROWS_PER_END:
    if end_number >= ENDS_PER_ROUND:
        session["end_number"] = 1
        session["round_number"] = round_number + 1
    else:
        session["end_number"] = end_number + 1
```

El avance se calcula consultando cuántas flechas tiene la tanda actual en la DB (fuente de verdad), no contando en memoria. Esto garantiza consistencia incluso si la sesión se recarga entre flechas.

---

### Bug 2 — Admin sin autenticación (`admin_routes.py` + `config.py`)

**Problema:** Ninguna ruta del blueprint `/admin` verifica si existe una sesión administrativa válida.

**Fix en tres partes:**

**Parte A — Credenciales en `config.py`:**

```python
# Variables de entorno (se leen de .env)
ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")
```

Las credenciales se leen del entorno, nunca hardcodeadas. En producción deben setearse como variables de entorno seguras.

**Parte B — Decorador `require_admin` en `admin_routes.py`:**

```python
import functools
from flask import session, redirect, url_for, current_app

def require_admin(view):
    """Decorador: redirige a /admin/login si no hay sesión de admin activa."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin.login"))
        return view(*args, **kwargs)
    return wrapped
```

Este decorador se aplica a **todas** las rutas existentes del blueprint admin:
- `tournaments()`
- `tournament_status()`
- `categories()`
- `archers()`
- `enroll()`
- `categories_json()`

**Parte C — Rutas de login/logout:**

```python
@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    """GET: renderiza formulario. POST: valida credenciales."""
    if session.get("admin_logged_in"):
        return redirect(url_for("admin.tournaments"))

    if request.method == "GET":
        return render_template("admin/login.html", error=None)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    cfg = current_app.config
    if username == cfg["ADMIN_USERNAME"] and password == cfg["ADMIN_PASSWORD"]:
        session["admin_logged_in"] = True
        session["admin_username"] = username
        return redirect(url_for("admin.tournaments"))

    return render_template("admin/login.html",
                           error="Credenciales incorrectas."), 401


@admin_bp.route("/logout", methods=["POST"])
def logout():
    session.pop("admin_logged_in", None)
    session.pop("admin_username", None)
    return redirect(url_for("admin.login"))
```

**Template `admin/login.html`:** Formulario simple con campos `username` y `password`, mensaje de error inline, sin información de diagnóstico en el error (mensaje genérico).

**`base.html`:** Los links de nav a `/admin/tournaments` y `/admin/archers` se reemplazan por un único link "Admin" que lleva a `/admin/login` cuando no hay sesión, o a `/admin/tournaments` cuando sí la hay (controlado con `session.get("admin_logged_in")` en el template).

---

### Bug 3 — Reset de datos de prueba (`admin_routes.py` + `admin.py`)

**Problema:** No existe mecanismo para eliminar arqueros sin acceso directo a la DB.

**Fix:** Añadir función `delete_archer()` en `admin.py` y ruta `DELETE`-style (POST con confirmación) en `admin_routes.py`.

**Regla de negocio:** Solo se puede eliminar un arquero que NO tiene inscripciones en torneos con status `active` o `finished`. Si tiene inscripciones históricas solo en torneos `created` (que aún no comenzaron), se permite.

```python
# archer/modules/admin.py

def delete_archer(archer_id: str) -> dict:
    """Elimina un arquero si no tiene inscripciones en torneos activos/finalizados.

    Retorna {} en éxito o {'error': str} en fallo.
    """
    conn = get_connection()

    # Verificar existencia
    cursor = conn.execute("SELECT id FROM archers WHERE id = ?", (archer_id,))
    if cursor.fetchone() is None:
        return {"error": "Arquero no encontrado.", "status_code": 404}

    # Verificar que no tiene participación en torneos activos o finalizados
    cursor = conn.execute(
        """
        SELECT r.id FROM registrations r
        JOIN tournaments t ON t.id = r.tournament_id
        WHERE r.archer_id = ?
          AND t.status IN ('active', 'finished')
        LIMIT 1
        """,
        (archer_id,),
    )
    if cursor.fetchone() is not None:
        return {
            "error": "No se puede eliminar: el arquero tiene participación en torneos activos o finalizados.",
            "status_code": 409,
        }

    # Eliminar inscripciones en torneos 'created' (limpieza en cascada manual)
    conn.execute(
        "DELETE FROM registrations WHERE archer_id = ?", (archer_id,)
    )
    conn.execute("DELETE FROM archers WHERE id = ?", (archer_id,))
    try:
        conn.commit()
    except Exception:
        pass
    return {}
```

**Ruta en `admin_routes.py`:**

```python
@admin_bp.route("/archers/<archer_id>/delete", methods=["POST"])
@require_admin
def delete_archer_route(archer_id: str):
    result = delete_archer(archer_id)
    if "error" in result:
        # re-renderizar con error
        ...
    return redirect(url_for("admin.archers"))
```

**UI:** En `admin/archers.html`, cada fila de arquero mostrará un botón "Eliminar" con confirmación `onclick="return confirm('...')"` que hace POST a `/admin/archers/<id>/delete`. El botón solo es visible si el arquero no tiene inscripciones activas (se puede indicar desde el template con un flag calculado en `list_archers()`).

---

### Bug 4 — UX torneos: accesos directos (`admin/tournaments.html`)

**Problema:** Las tarjetas de torneo no tienen links al leaderboard, stats ni arqueros inscritos.

**Fix:** Añadir tres nuevos botones de acción en el bloque de botones de cada tarjeta:

```html
<!-- Arqueros inscritos — siempre visible -->
<a href="{{ url_for('admin.enrolled_archers', tournament_id=t.id) }}"
   class="text-sm bg-purple-50 text-purple-700 border border-purple-200
          px-3 py-1.5 rounded-lg hover:bg-purple-100">
    Arqueros
</a>

<!-- Leaderboard en vivo — solo torneos activos -->
{% if t.status == 'active' %}
<a href="{{ url_for('leaderboard.view', tournament_id=t.id) }}"
   class="text-sm bg-green-50 text-green-700 border border-green-200
          px-3 py-1.5 rounded-lg hover:bg-green-100"
   target="_blank">
    Leaderboard
</a>
{% endif %}

<!-- Estadísticas — solo torneos finalizados -->
{% if t.status == 'finished' %}
<a href="{{ url_for('stats.tournament_view', tournament_id=t.id) }}"
   class="text-sm bg-indigo-50 text-indigo-700 border border-indigo-200
          px-3 py-1.5 rounded-lg hover:bg-indigo-100">
    Estadísticas
</a>
{% endif %}
```

**Nueva ruta `enrolled_archers`** en `admin_routes.py`:

```python
@admin_bp.route("/tournaments/<tournament_id>/archers", methods=["GET"])
@require_admin
def enrolled_archers(tournament_id: str):
    """Vista de arqueros inscritos en el torneo."""
    archers = list_enrolled_archers(tournament_id)
    tournament = get_tournament(tournament_id)
    return render_template("admin/enrolled_archers.html",
                           tournament=tournament, archers=archers)
```

**Nueva función `list_enrolled_archers`** en `admin.py` y nuevo template `admin/enrolled_archers.html`.

---

### Bug 5 — Eliminar torneos (`admin_routes.py` + `admin.py`)

**Problema:** No existe ruta ni función para eliminar torneos.

**Regla de negocio:** Solo torneos en estado `created` pueden eliminarse. Los torneos `active` o `finished` tienen datos de inscripción y score que no deben eliminarse por esta vía.

**Fix — `admin.py`:**

```python
def delete_tournament(tournament_id: str) -> dict:
    """Elimina un torneo en estado 'created' y sus categorías asociadas.

    No elimina torneos en estado 'active' o 'finished'.
    Retorna {} en éxito o {'error': str, 'status_code': int} en fallo.
    """
    conn = get_connection()

    cursor = conn.execute(
        "SELECT id, status FROM tournaments WHERE id = ?", (tournament_id,)
    )
    row = cursor.fetchone()
    if row is None:
        return {"error": "Torneo no encontrado.", "status_code": 404}

    if row["status"] != "created":
        return {
            "error": "Solo se pueden eliminar torneos en estado 'created'.",
            "status_code": 409,
        }

    # Eliminar en cascada: registrations → categories → tournament
    conn.execute(
        "DELETE FROM registrations WHERE tournament_id = ?", (tournament_id,)
    )
    conn.execute(
        "DELETE FROM categories WHERE tournament_id = ?", (tournament_id,)
    )
    conn.execute(
        "DELETE FROM tournaments WHERE id = ?", (tournament_id,)
    )
    try:
        conn.commit()
    except Exception:
        pass
    return {}
```

**Fix — `admin_routes.py`:**

```python
@admin_bp.route("/tournaments/<tournament_id>/delete", methods=["POST"])
@require_admin
def delete_tournament_route(tournament_id: str):
    result = delete_tournament(tournament_id)
    if "error" in result:
        status_code = result.get("status_code", 400)
        return render_template(
            "admin/tournaments.html",
            tournaments=list_tournaments(),
            error=result["error"],
            field=None,
            form_data={},
        ), status_code
    return redirect(url_for("admin.tournaments"))
```

**UI en `admin/tournaments.html`:** Botón "Eliminar" con confirmación JavaScript, visible solo cuando `t.status == 'created'`.

```html
{% if t.status == 'created' %}
<form method="POST"
      action="{{ url_for('admin.delete_tournament_route', tournament_id=t.id) }}"
      onsubmit="return confirm('¿Eliminar el torneo {{ t.name }}? Esta acción no se puede deshacer.')">
    <button type="submit"
            class="text-sm bg-red-50 text-red-700 border border-red-200
                   px-3 py-1.5 rounded-lg hover:bg-red-100">
        Eliminar
    </button>
</form>
{% endif %}
```

---

### Bug 6 — Stats no accesibles para arqueros (`stats_routes.py` + `archer/score.html`)

**Problema:** Las rutas de stats no tienen link desde la sesión del arquero y no verifican que el solicitante sea el arquero propietario.

**Fix en tres partes:**

**Parte A — Protección de rutas en `stats_routes.py`:**

```python
def _require_stats_access(archer_id: str) -> bool:
    """
    Retorna True si el solicitante tiene acceso a las stats del archer_id dado.
    
    Reglas:
    - Admin autenticado (session["admin_logged_in"]) → acceso a todo.
    - Arquero autenticado (session["archer_id"]) → solo sus propios datos.
    - Sin sesión → sin acceso.
    """
    if session.get("admin_logged_in"):
        return True
    return session.get("archer_id") == archer_id
```

Las rutas `trend()` y `trend_view()` verifican acceso:

```python
@stats_bp.route("/archer/<archer_id>/trend/view")
def trend_view(archer_id: str):
    if not _require_stats_access(archer_id):
        return redirect(url_for("archer.login"))
    result = archer_trend(archer_id)
    return render_template("stats/trend.html", trend=result)
```

La ruta JSON `/stats/archer/<archer_id>/trend` retorna 403 si no tiene acceso:

```python
@stats_bp.route("/archer/<archer_id>/trend")
def trend(archer_id: str):
    if not _require_stats_access(archer_id):
        return jsonify({"error": "Acceso no autorizado."}), 403
    result = archer_trend(archer_id)
    return jsonify(result), 200
```

Las rutas de torneo (`/stats/tournament/<id>`) son de solo lectura y no revelan datos privados de un arquero, por lo que se pueden dejar públicas (el leaderboard ya es público). Si se desea restringir, se puede añadir `require_admin` o dejarlo público para espectadores.

**Parte B — Link de stats en `archer/score.html`:**

Añadir un link discreto en el header del score screen, junto al botón de logout:

```html
<!-- En el bloque header de score.html -->
<div class="flex gap-2">
    <a href="{{ url_for('stats.trend_view', archer_id=session['archer_id']) }}"
       class="text-xs text-gray-500 border border-gray-300 rounded-lg px-3 py-1.5
              hover:bg-gray-100 active:bg-gray-200">
        Mis stats
    </a>
    <form method="POST" action="{{ url_for('archer.logout') }}">
        <button type="submit"
                class="text-xs text-gray-500 border border-gray-300 rounded-lg px-3 py-1.5
                       hover:bg-gray-100 active:bg-gray-200">
            Salir
        </button>
    </form>
</div>
```

El link solo se renderiza si hay sesión activa (la vista ya requiere `@require_session`).

**Parte C — Acceso admin a stats de todos los arqueros:**

En `admin/archers.html`, cada fila de arquero tendrá un link a sus stats:

```html
<a href="{{ url_for('stats.trend_view', archer_id=archer.id) }}"
   class="text-xs text-indigo-600 hover:underline">
    Ver stats
</a>
```

Dado que la ruta `trend_view` ya verifica `session.get("admin_logged_in")`, el admin puede navegar a las stats de cualquier arquero directamente desde el listado.

---

## Data Models

No se requieren cambios en el esquema de la base de datos. Todas las correcciones operan sobre el esquema existente:

```sql
-- Sin cambios de schema requeridos
-- archers, tournaments, categories, registrations, scores
-- permanecen igual
```

### Cambios en estructuras de sesión Flask

**Sesión del arquero** (sin cambios en keys, fix en lógica de incremento):
```python
session["archer_id"]    # str — UUID del arquero
session["archer_name"]  # str — nombre del arquero
session["last_active"]  # str — ISO timestamp
session["round_number"] # int — ronda actual (se incrementa correctamente)
session["end_number"]   # int — tanda actual (se incrementa correctamente)
```

**Sesión admin** (nuevo):
```python
session["admin_logged_in"]  # bool — True si autenticado
session["admin_username"]   # str  — username del admin
```

### Funciones nuevas en módulos

**`archer.py`:**
- `get_end_arrow_count(archer_id, tournament_id, round_number, end_number) -> int`

**`admin.py`:**
- `delete_tournament(tournament_id) -> dict`
- `delete_archer(archer_id) -> dict`
- `list_enrolled_archers(tournament_id) -> list[dict]`
- `get_tournament(tournament_id) -> dict | None`

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Avance de tanda tras completar N flechas

*For any* arquero con sesión activa y torneo activo, después de registrar exactamente `ARROWS_PER_END` flechas en una tanda dada, el valor de `session["end_number"]` debe incrementar en 1 (o `session["round_number"]` incrementar en 1 y `end_number` resetearse a 1 si se completaron todas las tandas de la ronda).

**Validates: Requirements 2.1**

### Property 2: Aislamiento de datos por tanda

*For any* conjunto de scores en la DB con múltiples combinaciones de `(round_number, end_number)`, `get_end_summary(archer_id, tournament_id, R, E)` debe retornar únicamente flechas donde `round_number = R AND end_number = E` para ese arquero y torneo, sin importar cuántas otras flechas existan con distintos valores de `round_number` o `end_number`.

**Validates: Requirements 2.2**

### Property 3: Protección universal de rutas admin

*For any* ruta dentro del blueprint `/admin` (excepto `/admin/login` y `/admin/logout`), una petición HTTP sin `session["admin_logged_in"] = True` debe resultar en HTTP 302 con `Location: /admin/login`, sin revelar ningún contenido protegido.

**Validates: Requirements 2.3**

### Property 4: Rechazo de credenciales incorrectas de admin

*For any* par `(username, password)` que no coincida exactamente con `ADMIN_USERNAME` y `ADMIN_PASSWORD` configurados, el endpoint `POST /admin/login` debe retornar HTTP 401 y NO establecer `session["admin_logged_in"]`.

**Validates: Requirements 2.5**

### Property 5: Eliminación de torneo elimina también sus categorías y registraciones

*For any* torneo en estado `created` con un número arbitrario de categorías y registraciones, después de invocar `delete_tournament(tournament_id)`, ni el torneo, ni ninguna de sus categorías, ni ninguna de sus registraciones deben estar presentes en la DB.

**Validates: Requirements 2.8**

### Property 6: Solo arqueros sin participación activa pueden eliminarse

*For any* arquero, `delete_archer(archer_id)` debe tener éxito (retornar `{}`) si y solo si el arquero no tiene ninguna inscripción en torneos con estado `active` o `finished`. Si tiene al menos una inscripción en un torneo activo o finalizado, debe retornar `{"error": ..., "status_code": 409}`.

**Validates: Requirements 2.9**

### Property 7: Aislamiento de datos de stats por arquero

*For any* arquero autenticado con `archer_id = A`, el endpoint `/stats/archer/<archer_id>/trend` o `/stats/archer/<archer_id>/trend/view` con `archer_id ≠ A` debe retornar HTTP 403 (JSON) o HTTP 302 a login (HTML), sin exponer ningún dato de otro arquero.

**Validates: Requirements 2.11**

---

## Error Handling

### Bug 1 — Avance de tanda
- Si `get_end_arrow_count` falla por error de DB, se captura la excepción, se loguea, y se redirige sin incrementar el estado de sesión (comportamiento seguro: el arquero permanece en la tanda actual).
- Si `ARROWS_PER_END` o `ENDS_PER_ROUND` están mal configurados (≤ 0), se usa el valor por defecto de 6 y 10 respectivamente.

### Bug 2 — Admin auth
- Credenciales vacías: el formulario HTML tiene `required` en ambos campos. En el servidor, si `ADMIN_PASSWORD` está vacío en el entorno (no configurado), el login siempre falla con mensaje de error genérico.
- El mensaje de error es deliberadamente genérico ("Credenciales incorrectas") sin indicar cuál campo es incorrecto (anti-user-enumeration).
- Logging: cada intento de login fallido se loguea con `logger.warning("Admin login failed for username=%s", username)` sin loguear la contraseña.

### Bug 3 — Reset de datos
- Intento de eliminar arquero inexistente → 404.
- Intento de eliminar arquero con participación activa → 409 con mensaje explicativo.
- Error de DB durante delete → 500, se revierte (SQLite/libSQL son ACID).

### Bug 5 — Eliminar torneo
- Intento de eliminar torneo `active` o `finished` → 409.
- Torneo no encontrado → 404.
- La confirmación JavaScript es la primera línea de defensa; el servidor siempre verifica el estado del torneo independientemente.

### Bug 6 — Stats auth
- Acceso sin sesión a ruta HTML → redirect 302 a `/archer/login`.
- Acceso sin sesión a ruta JSON → 403 con `{"error": "Acceso no autorizado."}`.
- Admin siempre puede acceder a stats de cualquier arquero.

---

## Testing Strategy

### Enfoque dual: unit tests + property-based tests

Se usa **pytest** para unit tests y **Hypothesis** para property-based tests. La app Flask se testea con `app.test_client()` en modo `TESTING=True` con SQLite en memoria (`:memory:`).

### Configuración de Hypothesis

```python
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(...)
def test_property_N(...):
    ...
```

### Tests por bug

#### Bug 1 — Avance de tanda

**Property test (Property 1):** Generar un `archer_id` válido con `n_arrows` de 1 a `ARROWS_PER_END`. Verificar que cuando `n_arrows >= ARROWS_PER_END`, `session["end_number"]` incrementa.

**Property test (Property 2):** Generar una base de datos de scores con flechas distribuidas aleatoriamente en múltiples `(round_number, end_number)`. Verificar que `get_end_summary(archer_id, tournament_id, R, E)` solo retorna las flechas del par `(R, E)`.

**Unit test:** Registrar 6 flechas consecutivas y verificar que `end_number` es 2 al final.

#### Bug 2 — Admin auth

**Property test (Property 3):** Enumerar todas las rutas admin registradas en el blueprint. Para cada una, enviar request sin sesión y verificar redirect a `/admin/login`.

**Property test (Property 4):** Generar pares `(username, password)` aleatorios que no coincidan con las credenciales correctas. Verificar que todos devuelven 401 y no establecen `session["admin_logged_in"]`.

**Unit test:** Login correcto → session establecida + redirect a `/admin/tournaments`.

**Unit test:** Login incorrecto → 401 + sin sesión.

#### Bug 3 — Reset de datos

**Property test (Property 6):** Generar arqueros con y sin inscripciones en torneos de diferentes estados. Verificar que `delete_archer` solo tiene éxito para arqueros sin participación activa/finalizada.

**Unit test:** Eliminar arquero existente sin inscripciones → OK.

**Unit test:** Eliminar arquero con inscripción en torneo `active` → 409.

#### Bug 4 — UX torneos

**Unit test (Example):** Renderizar `tournaments.html` con un torneo `active` y verificar que el HTML contiene el link al leaderboard.

**Unit test (Example):** Renderizar `tournaments.html` con un torneo `finished` y verificar que el HTML contiene el link a estadísticas.

**Unit test (Example):** Renderizar `tournaments.html` con cualquier torneo y verificar que el HTML contiene el link a arqueros inscritos.

#### Bug 5 — Eliminar torneo

**Property test (Property 5):** Generar torneos en estado `created` con un número aleatorio de categorías (0 a 10) y registraciones. Verificar que `delete_tournament` elimina en cascada todos los registros asociados.

**Unit test:** Intentar eliminar torneo `active` → error 409.

**Unit test:** Intentar eliminar torneo `finished` → error 409.

#### Bug 6 — Stats auth

**Property test (Property 7):** Generar pares de `archer_id` distintos. Autenticar como arquero A. Intentar acceder a stats del arquero B. Verificar 403 (JSON) o redirect (HTML).

**Unit test (Example):** Admin autenticado accede a stats de cualquier arquero → 200.

**Unit test (Example):** Arquero autenticado accede a sus propias stats → 200.

**Unit test (Example):** `score.html` renderizado con sesión activa contiene el link "Mis stats".

## Glossary

- **End / Tanda:** Grupo de flechas disparadas en una sola posición en el blanco antes de avanzar. El número estándar es 3 o 6 flechas por tanda (World Archery).
- **Round / Ronda:** Conjunto de tandas. Una ronda completa típicamente consiste en 10 tandas.
- **ARROWS_PER_END:** Constante configurable que define cuántas flechas forman una tanda. Valor por defecto: 6.
- **ENDS_PER_ROUND:** Constante configurable que define cuántas tandas forman una ronda. Valor por defecto: 10.
- **PRG (Post-Redirect-Get):** Patrón web que evita el reenvío de formularios al hacer redirect HTTP 302 tras un POST exitoso.
- **Sesión admin:** Cookie de sesión Flask con `session["admin_logged_in"] = True`, establecida tras login correcto en `/admin/login`.
- **Sesión archer:** Cookie de sesión Flask con `session["archer_id"]` y `session["end_number"]`, establecida tras login PIN correcto.
- **Cascade delete:** Eliminación de registros relacionados en cadena (ej. al borrar un torneo, se borran también sus categorías y registraciones).
- **Stats isolation:** Propiedad de seguridad que garantiza que un arquero solo puede ver sus propios datos estadísticos.

### Regression tests (Unchanged Behavior)

Para cada punto de la sección 3.x del bugfix.md, se debe verificar que el comportamiento anterior se preserva:

- **3.1–3.2:** Guardar flecha en torneo activo → score persiste con `arrow_val` y `points` correctos.
- **3.3–3.4:** PIN correcto autentica; 5 intentos fallidos bloquean.
- **3.5–3.6:** Crear torneo y cambiar estado siguen funcionando.
- **3.7:** Crear categoría única funciona.
- **3.8–3.9:** SSE del leaderboard emite en ≤ 2s; ranking global retorna solo torneos `finished`.
- **3.10–3.11:** PIN incorrecto redirige a login.

Estos tests ya deben existir en el suite de tests. Se ejecuta `pytest tests/` para verificar que no hay regresiones tras aplicar los fixes.
