# Implementation Plan: archer-app-fixes

## Overview

Corrección quirúrgica de seis bugs críticos en KiroArchery (Flask + Turso/libSQL). Cada tarea modifica únicamente los archivos que presentan el defecto. El orden de implementación va de la base hacia arriba: primero la capa de módulos (`archer.py`, `admin.py`), luego las rutas (`archer_routes.py`, `admin_routes.py`, `stats_routes.py`) y finalmente los templates HTML.

## Tasks

- [x] 1. Bug 1 — Añadir constantes y función `get_end_arrow_count` en `archer.py`
  - [x] 1.1 Agregar `ARROWS_PER_END = 6` y `ENDS_PER_ROUND = 10` como constantes de módulo en `archer/modules/archer.py`
    - Definir las constantes al inicio del módulo, antes de las funciones
    - _Requirements: 2.1_

  - [x] 1.2 Implementar `get_end_arrow_count(archer_id, tournament_id, round_number, end_number) -> int` en `archer/modules/archer.py`
    - Ejecutar `SELECT COUNT(*) FROM scores WHERE archer_id=? AND tournament_id=? AND round_number=? AND end_number=?`
    - Retornar `int(row["cnt"])` si hay resultado, o `0` si no
    - _Requirements: 2.1_

  - [ ]* 1.3 Escribir property test para `get_end_arrow_count` (Property 2)
    - **Property 2: Aislamiento de datos por tanda**
    - Generar flechas distribuidas aleatoriamente en múltiples `(round_number, end_number)` con Hypothesis
    - Verificar que `get_end_arrow_count(A, T, R, E)` solo cuenta flechas del par `(R, E)` exacto
    - **Validates: Requirements 2.2**

- [x] 2. Bug 1 — Implementar lógica de avance de tanda en `score_post()` de `archer_routes.py`
  - [x] 2.1 Modificar `score_post()` en `archer_routes.py` para llamar a `get_end_arrow_count` tras guardar la flecha
    - Importar `get_end_arrow_count`, `ARROWS_PER_END`, `ENDS_PER_ROUND` desde `archer.py`
    - Después del save exitoso: si `arrow_count >= ARROWS_PER_END`, incrementar `session["end_number"]` o hacer rollover de ronda
    - Lógica de rollover: si `end_number >= ENDS_PER_ROUND` → `session["round_number"] += 1`, `session["end_number"] = 1`; si no → `session["end_number"] += 1`
    - _Requirements: 2.1, 2.2_

  - [ ]* 2.2 Escribir property test para avance de tanda (Property 1)
    - **Property 1: Avance de tanda tras completar N flechas**
    - Usar `app.test_client()` con SQLite en memoria; generar `n_arrows` de 1 a `ARROWS_PER_END` vía Hypothesis
    - Verificar que cuando `n_arrows >= ARROWS_PER_END`, el redirect deja `session["end_number"]` incrementado (o `round_number` incrementado y `end_number = 1`)
    - **Validates: Requirements 2.1**

  - [ ]* 2.3 Escribir unit test de ejemplo para avance completo de tanda
    - Registrar 6 flechas consecutivas via test client y verificar que `session["end_number"] == 2` al final
    - Registrar `ENDS_PER_ROUND * ARROWS_PER_END` flechas y verificar que `session["round_number"] == 2` y `session["end_number"] == 1`
    - _Requirements: 2.1, 2.2_

- [x] 3. Checkpoint — Bug 1 completo
  - Asegurar que todos los tests del Bug 1 pasan. Preguntar al usuario si tiene dudas antes de continuar.

- [x] 4. Bug 2 — Añadir credenciales admin en `config.py` y decorador `require_admin` en `admin_routes.py`
  - [x] 4.1 Leer `ADMIN_USERNAME` y `ADMIN_PASSWORD` desde variables de entorno en `config.py`
    - Usar `os.environ.get("ADMIN_USERNAME", "admin")` y `os.environ.get("ADMIN_PASSWORD", "")`
    - _Requirements: 2.4, 2.5_

  - [x] 4.2 Implementar decorador `require_admin` en `admin_routes.py`
    - Usar `functools.wraps`; verificar `session.get("admin_logged_in")`; redirigir a `url_for("admin.login")` si no hay sesión
    - _Requirements: 2.3_

  - [x] 4.3 Aplicar `@require_admin` a todas las rutas admin existentes en `admin_routes.py`
    - Decorar: `tournaments()`, `tournament_status()`, `categories()`, `archers()`, `enroll()`, `categories_json()`
    - _Requirements: 2.3_

  - [ ]* 4.4 Escribir property test para protección universal de rutas admin (Property 3)
    - **Property 3: Protección universal de rutas admin**
    - Enumerar todas las rutas del blueprint `/admin` excepto `/admin/login` y `/admin/logout`
    - Para cada ruta, enviar request GET/POST sin sesión y verificar HTTP 302 con `Location` apuntando a `/admin/login`
    - **Validates: Requirements 2.3**

- [x] 5. Bug 2 — Agregar rutas de login/logout y template en `admin_routes.py`
  - [x] 5.1 Implementar `GET/POST /admin/login` en `admin_routes.py`
    - GET: render `admin/login.html` con `error=None`; si ya hay sesión, redirect a `admin.tournaments`
    - POST: comparar `username` y `password` con `cfg["ADMIN_USERNAME"]` y `cfg["ADMIN_PASSWORD"]`; si OK → `session["admin_logged_in"] = True`, redirect a `admin.tournaments`; si no → render con `error="Credenciales incorrectas."`, status 401
    - Loguear intentos fallidos con `logger.warning(...)` sin incluir la contraseña
    - _Requirements: 2.4, 2.5_

  - [ ] 5.2 Implementar `POST /admin/logout` en `admin_routes.py`
    - Hacer pop de `session["admin_logged_in"]` y `session["admin_username"]`; redirect a `admin.login`
    - _Requirements: 2.3_

  - [x] 5.3 Crear template `templates/admin/login.html`
    - Formulario con campos `username` (required) y `password` (required), botón submit
    - Mostrar `error` inline si no es `None`; mensaje genérico sin indicar qué campo falló
    - Estilos Tailwind CSS, diseño mobile-first
    - _Requirements: 2.4, 2.5_

  - [x] 5.4 Actualizar links de nav admin en `base.html`
    - Reemplazar links directos a `/admin/tournaments` y `/admin/archers` por lógica condicional: si `session.get("admin_logged_in")` → link a `/admin/tournaments`; si no → link a `/admin/login`
    - _Requirements: 2.3_

  - [ ]* 5.5 Escribir property test para rechazo de credenciales incorrectas (Property 4)
    - **Property 4: Rechazo de credenciales incorrectas de admin**
    - Generar pares `(username, password)` aleatorios con Hypothesis que no coincidan con las credenciales correctas
    - Verificar que todos devuelven HTTP 401 y que `session["admin_logged_in"]` NO está seteado
    - **Validates: Requirements 2.5**

  - [ ]* 5.6 Escribir unit tests de ejemplo para login admin
    - Test: login correcto → sesión establecida + redirect 302 a `/admin/tournaments`
    - Test: login incorrecto → 401 + sin sesión
    - _Requirements: 2.4, 2.5_

- [x] 6. Checkpoint — Bug 2 completo
  - Asegurar que todos los tests del Bug 2 pasan. Preguntar al usuario si tiene dudas antes de continuar.

- [x] 7. Bug 3 — Implementar `delete_archer` en `admin.py` y ruta en `admin_routes.py`
  - [x] 7.1 Implementar `delete_archer(archer_id: str) -> dict` en `admin/modules/admin.py`
    - Verificar existencia del arquero; si no existe retornar `{"error": "...", "status_code": 404}`
    - Verificar que no tiene inscripciones en torneos con `status IN ('active', 'finished')`; si tiene retornar `{"error": "...", "status_code": 409}`
    - Eliminar inscripciones en torneos `created` y luego el arquero; hacer commit; retornar `{}`
    - _Requirements: 2.9_

  - [x] 7.2 Agregar ruta `POST /admin/archers/<archer_id>/delete` en `admin_routes.py`
    - Aplicar `@require_admin`
    - Llamar a `delete_archer(archer_id)`; si hay error re-renderizar `admin/archers.html` con el mensaje de error
    - Si OK, redirect a `url_for("admin.archers")`
    - _Requirements: 2.9_

  - [x] 7.3 Actualizar `templates/admin/archers.html` para mostrar botón "Eliminar" por fila
    - Agregar un `<form method="POST">` con `action` a `/admin/archers/<id>/delete` y `onsubmit="return confirm('...')"` por cada arquero
    - Botón con estilos Tailwind (rojo suave, border)
    - _Requirements: 2.9_

  - [ ]* 7.4 Escribir property test para lógica de eliminación de arqueros (Property 6)
    - **Property 6: Solo arqueros sin participación activa pueden eliminarse**
    - Usar Hypothesis para generar arqueros con inscripciones en torneos de distintos estados
    - Verificar que `delete_archer` retorna `{}` si y solo si el arquero no tiene inscripciones en torneos `active` o `finished`
    - **Validates: Requirements 2.9**

  - [ ]* 7.5 Escribir unit tests de ejemplo para `delete_archer`
    - Test: eliminar arquero sin inscripciones → OK (200 + redirect)
    - Test: eliminar arquero con inscripción en torneo `active` → 409 con mensaje
    - Test: eliminar arquero inexistente → 404
    - _Requirements: 2.9_

- [ ] 8. Bug 4 — Nuevas funciones en `admin.py` y ruta de arqueros inscritos en `admin_routes.py`
  - [x] 8.1 Implementar `list_enrolled_archers(tournament_id: str) -> list[dict]` en `admin/modules/admin.py`
    - Query: JOIN de `registrations`, `archers` y `categories` filtrando por `tournament_id`
    - Retornar lista de dicts con campos: `archer_id`, `archer_name`, `category` (bow_type + distance + gender)
    - _Requirements: 2.7_

  - [x] 8.2 Implementar `get_tournament(tournament_id: str) -> dict | None` en `admin/modules/admin.py`
    - Query simple: `SELECT * FROM tournaments WHERE id = ?`
    - Retornar dict con los campos del torneo o `None` si no existe
    - _Requirements: 2.6, 2.7_

  - [x] 8.3 Agregar ruta `GET /admin/tournaments/<tournament_id>/archers` en `admin_routes.py`
    - Aplicar `@require_admin`
    - Llamar a `list_enrolled_archers(tournament_id)` y `get_tournament(tournament_id)`
    - Render `admin/enrolled_archers.html` con `tournament` y `archers`
    - _Requirements: 2.7_

  - [x] 8.4 Crear template `templates/admin/enrolled_archers.html`
    - Mostrar nombre del torneo como título
    - Tabla con columnas: nombre del arquero, categoría (bow_type / distance / gender)
    - Link "Volver" al listado de torneos; estilos Tailwind
    - _Requirements: 2.7_

  - [x] 8.5 Actualizar `templates/admin/tournaments.html` con los nuevos botones de acción
    - Botón "Arqueros" → `url_for('admin.enrolled_archers', tournament_id=t.id)` (siempre visible)
    - Botón "Leaderboard" → `url_for('leaderboard.view', tournament_id=t.id)` (solo si `t.status == 'active'`), abrir en `target="_blank"`
    - Botón "Estadísticas" → `url_for('stats.tournament_view', tournament_id=t.id)` (solo si `t.status == 'finished'`)
    - Estilos Tailwind diferenciados por tipo de acción (púrpura para arqueros, verde para leaderboard, índigo para stats)
    - _Requirements: 2.6, 2.7_

  - [ ]* 8.6 Escribir unit tests de ejemplo para UX de torneos
    - Test: renderizar `tournaments.html` con torneo `active` → HTML contiene link a leaderboard y link a arqueros, pero NO link a estadísticas
    - Test: renderizar `tournaments.html` con torneo `finished` → HTML contiene link a estadísticas y link a arqueros, pero NO link a leaderboard
    - Test: renderizar `tournaments.html` con torneo `created` → HTML contiene solo link a arqueros
    - _Requirements: 2.6, 2.7_

- [x] 9. Bug 5 — Implementar `delete_tournament` en `admin.py` y ruta en `admin_routes.py`
  - [x] 9.1 Implementar `delete_tournament(tournament_id: str) -> dict` en `admin/modules/admin.py`
    - Verificar existencia; si no existe retornar `{"error": "...", "status_code": 404}`
    - Verificar que `status == 'created'`; si no retornar `{"error": "Solo se pueden eliminar torneos en estado 'created'.", "status_code": 409}`
    - Eliminar en cascada: `registrations` → `categories` → `tournaments`; hacer commit; retornar `{}`
    - _Requirements: 2.8_

  - [x] 9.2 Agregar ruta `POST /admin/tournaments/<tournament_id>/delete` en `admin_routes.py`
    - Aplicar `@require_admin`
    - Llamar a `delete_tournament(tournament_id)`; si hay error re-renderizar `admin/tournaments.html` con el error
    - Si OK, redirect a `url_for("admin.tournaments")`
    - _Requirements: 2.8_

  - [x] 9.3 Actualizar `templates/admin/tournaments.html` para mostrar botón "Eliminar" en torneos `created`
    - Botón visible solo cuando `t.status == 'created'` usando `{% if t.status == 'created' %}`
    - `<form method="POST">` con `onsubmit="return confirm('¿Eliminar el torneo {{ t.name }}? Esta acción no se puede deshacer.')"` 
    - Estilos Tailwind (rojo suave)
    - _Requirements: 2.8_

  - [ ]* 9.4 Escribir property test para eliminación de torneos en cascada (Property 5)
    - **Property 5: Eliminación de torneo elimina también sus categorías y registraciones**
    - Usar Hypothesis para generar torneos `created` con 0–10 categorías y un número aleatorio de registraciones
    - Verificar que tras `delete_tournament(id)` ni el torneo, ni sus categorías, ni sus registraciones están en la DB
    - **Validates: Requirements 2.8**

  - [ ]* 9.5 Escribir unit tests de ejemplo para `delete_tournament`
    - Test: eliminar torneo `created` con categorías y registraciones → todas las filas eliminadas en cascada
    - Test: eliminar torneo `active` → 409 con mensaje
    - Test: eliminar torneo inexistente → 404
    - _Requirements: 2.8_

- [x] 10. Checkpoint — Bugs 3, 4 y 5 completos
  - Asegurar que todos los tests de los Bugs 3, 4 y 5 pasan. Preguntar al usuario si tiene dudas antes de continuar.

- [x] 11. Bug 6 — Proteger rutas de stats y añadir accesos desde sesión del arquero
  - [x] 11.1 Implementar `_require_stats_access(archer_id: str) -> bool` en `stats_routes.py`
    - Retornar `True` si `session.get("admin_logged_in")` es verdadero
    - Retornar `True` si `session.get("archer_id") == archer_id`
    - Retornar `False` en cualquier otro caso
    - _Requirements: 2.11, 2.12_

  - [x] 11.2 Aplicar control de acceso en `trend_view()` en `stats_routes.py`
    - Llamar a `_require_stats_access(archer_id)` al inicio de la función
    - Si retorna `False`, hacer redirect a `url_for("archer.login")`
    - _Requirements: 2.11_

  - [x] 11.3 Aplicar control de acceso en `trend()` (ruta JSON) en `stats_routes.py`
    - Llamar a `_require_stats_access(archer_id)` al inicio de la función
    - Si retorna `False`, retornar `jsonify({"error": "Acceso no autorizado."})` con status 403
    - _Requirements: 2.11_

  - [x] 11.4 Agregar link "Mis stats" en `templates/archer/score.html`
    - Añadir `<a href="{{ url_for('stats.trend_view', archer_id=session['archer_id']) }}">Mis stats</a>` en el header junto al botón "Salir"
    - Usar estilos Tailwind consistentes con el botón de salida existente
    - _Requirements: 2.10_

  - [x] 11.5 Agregar link "Ver stats" por arquero en `templates/admin/archers.html`
    - Añadir `<a href="{{ url_for('stats.trend_view', archer_id=archer.id) }}">Ver stats</a>` en cada fila del listado
    - Estilo discreto (texto índigo, hover subrayado)
    - _Requirements: 2.12_

  - [ ]* 11.6 Escribir property test para aislamiento de stats por arquero (Property 7)
    - **Property 7: Aislamiento de datos de stats por arquero**
    - Usar Hypothesis para generar pares `(logged_in_archer_id, target_archer_id)` donde ambos son distintos
    - Para la ruta HTML: verificar que retorna 302 a login cuando no hay sesión o cuando `archer_id` de sesión ≠ `target_archer_id`
    - Para la ruta JSON: verificar que retorna 403 con `{"error": ...}` en los mismos casos
    - **Validates: Requirements 2.11**

  - [ ]* 11.7 Escribir unit tests de ejemplo para control de acceso a stats
    - Test: arquero A accede a stats de arquero A → 200 OK
    - Test: arquero A accede a stats de arquero B → 403 (JSON) / 302 (HTML)
    - Test: admin accede a stats de cualquier arquero → 200 OK
    - Test: sin sesión → 403 (JSON) / 302 a login (HTML)
    - _Requirements: 2.11, 2.12_

- [x] 12. Checkpoint final — Todos los bugs completos
  - Asegurar que todos los tests de todos los bugs pasan. Verificar que los comportamientos de regresión (sección 3.x del bugfix.md) no fueron afectados. Preguntar al usuario si tiene dudas.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para una corrección más rápida
- Cada tarea referencia los requisitos específicos del `bugfix.md` para trazabilidad
- Los property tests usan pytest + Hypothesis con `app.test_client()` en modo `TESTING=True` y SQLite en memoria
- El decorador `@require_admin` debe estar definido **antes** de las rutas que lo usan en `admin_routes.py`
- Las eliminaciones en cascada son manuales (no hay `ON DELETE CASCADE` en el schema actual)
- Los templates usan Tailwind CSS via CDN y Alpine.js para interactividad mínima

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "4.1", "4.2"] },
    { "id": 2, "tasks": ["1.3", "2.1", "4.3", "7.1", "8.1", "8.2", "9.1", "11.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "4.4", "5.1", "5.2", "7.2", "8.3", "9.2", "11.2", "11.3"] },
    { "id": 4, "tasks": ["5.3", "5.4", "7.3", "8.4", "8.5", "9.3", "11.4", "11.5"] },
    { "id": 5, "tasks": ["5.5", "5.6", "7.4", "7.5", "8.6", "9.4", "9.5", "11.6", "11.7"] }
  ]
}
```
