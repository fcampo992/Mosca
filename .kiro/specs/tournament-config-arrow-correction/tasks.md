# Implementation Plan: tournament-config-arrow-correction

## Overview

Implementación incremental de dos funcionalidades en KiroArchery: configuración de rondas y flechas por torneo (reemplazando las constantes hardcodeadas), y corrección de flechas por el arquero (tanda activa) y por el administrador (cualquier ronda). El orden sigue las dependencias naturales: esquema DB → módulos de negocio → rutas → templates → tests.

**Stack:** Python 3.12+ · Flask · Turso (libsql-experimental / sqlite3 fallback) · Jinja2 · Alpine.js · Tailwind CSS CDN · pytest + Hypothesis

---

## Tasks

- [x] 1. Migración de esquema — añadir columnas `rounds` y `arrows_per_end` a `tournaments`
  - [x] 1.1 Actualizar `init_db()` en `archer/db.py` para incluir las nuevas columnas en el `CREATE TABLE IF NOT EXISTS`
    - Añadir `rounds INTEGER NOT NULL DEFAULT 10` y `arrows_per_end INTEGER NOT NULL DEFAULT 6` al DDL de `tournaments`
    - Añadir bloque de migraciones seguras al final de `init_db()`: ejecutar `ALTER TABLE tournaments ADD COLUMN rounds INTEGER NOT NULL DEFAULT 10` y `ALTER TABLE tournaments ADD COLUMN arrows_per_end INTEGER NOT NULL DEFAULT 6` dentro de `try/except OperationalError` para tolerar columnas ya existentes
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ]* 1.2 Escribir smoke test para verificar columnas en el esquema
    - Test: tras llamar `init_db()`, `PRAGMA table_info(tournaments)` incluye `rounds` y `arrows_per_end` con sus defaults
    - Test: llamar `init_db()` dos veces sobre la misma BD no lanza excepción (idempotencia)
    - _Requirements: 5.1, 5.2_

  - [ ]* 1.3 Escribir property test — retrocompatibilidad de migración (Property 13)
    - **Feature: tournament-config-arrow-correction, Property 13: Retrocompatibilidad de migración — defaults en registros existentes**
    - Crear torneos SIN las columnas nuevas (simulando BD pre-migración), ejecutar `init_db()`, verificar que todos los registros tienen `rounds = 10` y `arrows_per_end = 6` y que los demás campos no cambiaron
    - **Validates: Requirement 5.3**

- [x] 2. Admin_Module — actualizar `create_tournament()` y añadir validaciones
  - [x] 2.1 Actualizar la firma y el cuerpo de `create_tournament()` en `archer/modules/admin.py`
    - Añadir parámetros `rounds: int = 10` y `arrows_per_end: int = 6` a la firma
    - Añadir validación de `rounds`: convertir a `int`, rechazar si no está en `[1, 20]` → retornar `{"error": "Las rondas deben estar entre 1 y 20.", "field": "rounds"}`
    - Añadir validación de `arrows_per_end`: convertir a `int`, rechazar si no está en `[1, 12]` → retornar `{"error": "Las flechas por tanda deben estar entre 1 y 12.", "field": "arrows_per_end"}`
    - Incluir `rounds` y `arrows_per_end` en el `INSERT` y en el dict retornado en caso de éxito
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ]* 2.2 Escribir property test — persistencia de configuración de torneo (Property 1)
    - **Feature: tournament-config-arrow-correction, Property 1: Persistencia de configuración de torneo (round-trip)**
    - `@given(rounds=st.integers(1,20), arrows_per_end=st.integers(1,12))`; crear torneo, recuperarlo de la BD, verificar que `rounds` y `arrows_per_end` son idénticos a los proporcionados
    - **Validates: Requirement 1.1**

  - [ ]* 2.3 Escribir property test — rechazo de `rounds` fuera de rango (Property 2)
    - **Feature: tournament-config-arrow-correction, Property 2: Rechazo de rounds fuera del rango válido**
    - `@given(rounds=st.one_of(st.integers(max_value=0), st.integers(min_value=21)))`; verificar error con `field='rounds'` y que no se crea ningún registro
    - **Validates: Requirement 1.3**

  - [ ]* 2.4 Escribir property test — rechazo de `arrows_per_end` fuera de rango (Property 3)
    - **Feature: tournament-config-arrow-correction, Property 3: Rechazo de arrows_per_end fuera del rango válido**
    - `@given(arrows_per_end=st.one_of(st.integers(max_value=0), st.integers(min_value=13)))`; verificar error con `field='arrows_per_end'` y que no se crea ningún registro
    - **Validates: Requirement 1.4**

- [x] 3. Archer_Module — actualizar `get_active_tournament()` para exponer nuevas columnas
  - [x] 3.1 Modificar el SELECT en `get_active_tournament()` dentro de `archer/modules/archer.py`
    - Incluir `t.rounds` y `t.arrows_per_end` en el `SELECT` de la consulta que hace JOIN entre `registrations` y `tournaments`
    - Asegurar que el dict retornado expone los campos `rounds` y `arrows_per_end`
    - _Requirements: 2.4_

- [x] 4. Archer_Module — implementar `correct_arrow_archer()`
  - [x] 4.1 Implementar `correct_arrow_archer(score_id, arrow_val, archer_id, tournament_id, current_round, current_end)` en `archer/modules/archer.py`
    - Validar `arrow_val` contra `["X","10","9","8","7","6","5","4","3","2","1","M"]` → `{"error": "...", "field": "arrow_val"}` si inválido
    - Buscar el score por `score_id`; si no existe o no pertenece al `archer_id`/`tournament_id` → `{"error": "...", "status_code": 403}`
    - Verificar que pertenece a la tanda activa (`round_number == current_round AND end_number == current_end`); si pertenece a ronda confirmada → `{"error": "Solo un administrador puede corregir rondas confirmadas.", "status_code": 403}`
    - Aplicar mapeo `arrow_val → points` (`X`→10, `10`→10, `9–1`→9–1, `M`→0), ejecutar `UPDATE scores SET arrow_val=?, points=? WHERE id=?`
    - Llamar a `broadcast_update(tournament_id)` tras el UPDATE exitoso
    - Retornar dict con los campos actualizados del score
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 6.1, 6.2_

  - [ ]* 4.2 Escribir property test — invariante de mapeo `arrow_val → points` (Property 6)
    - **Feature: tournament-config-arrow-correction, Property 6: Corrección de flecha en tanda activa — invariante de mapeo**
    - `@given(arrow_val=st.sampled_from(["X","10","9","8","7","6","5","4","3","2","1","M"]))`; crear score, corregirlo, verificar que `points` == valor del mapping
    - **Validates: Requirements 3.1, 6.1**

  - [ ]* 4.3 Escribir property test — round-trip de doble corrección (Property 7)
    - **Feature: tournament-config-arrow-correction, Property 7: Corrección de flecha — round-trip de doble corrección**
    - Corregir flecha de `v1` a `v2`, luego de `v2` a `v1`; verificar que `arrow_val` y `points` son idénticos al estado original
    - **Validates: Requirement 6.2**

  - [ ]* 4.4 Escribir property test — rechazo de `arrow_val` inválido (Property 8 — arquero)
    - **Feature: tournament-config-arrow-correction, Property 8: Rechazo de corrección de flecha con arrow_val inválido**
    - `@given(arrow_val=st.text())` filtrado para excluir los 12 valores válidos; verificar error con `field='arrow_val'` y sin modificación de la BD
    - **Validates: Requirement 3.3**

  - [ ]* 4.5 Escribir property test — rechazo de ronda confirmada por el arquero (Property 9)
    - **Feature: tournament-config-arrow-correction, Property 9: Rechazo de corrección de ronda confirmada por el arquero**
    - Generar scores con `round_number < current_round` o `end_number < current_end`; verificar HTTP 403 y sin modificación
    - **Validates: Requirement 3.2**

  - [ ]* 4.6 Escribir property test — rechazo de flecha ajena al arquero (Property 10)
    - **Feature: tournament-config-arrow-correction, Property 10: Rechazo de corrección de flecha ajena al arquero (HTTP 403)**
    - Intentar corregir `score_id` que pertenece a otro `archer_id`; verificar HTTP 403 y sin modificación
    - **Validates: Requirement 3.4**

- [ ] 5. Admin_Module — implementar `correct_arrow_admin()`
  - [x] 5.1 Implementar `correct_arrow_admin(score_id, arrow_val)` en `archer/modules/admin.py`
    - Validar `arrow_val` contra los 12 valores válidos → `{"error": "...", "field": "arrow_val"}` si inválido
    - Buscar el score por `score_id`; si no existe → `{"error": "...", "status_code": 404}`
    - Aplicar mapeo `arrow_val → points`, ejecutar `UPDATE scores SET arrow_val=?, points=? WHERE id=?`
    - Llamar a `broadcast_update(tournament_id)` del score actualizado
    - Retornar dict con los campos actualizados del score
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 6.1, 6.2_

  - [ ]* 5.2 Escribir property test — corrección administrativa sin restricción de ronda (Property 12)
    - **Feature: tournament-config-arrow-correction, Property 12: Corrección administrativa — sin restricción de ronda**
    - `@given(round_number=st.integers(1,20), end_number=st.integers(1,20), arrow_val=st.sampled_from(...))`; verificar que `correct_arrow_admin()` actualiza correctamente independientemente de `round_number`/`end_number`
    - **Validates: Requirement 4.1**

  - [ ]* 5.3 Escribir property test — rechazo de `arrow_val` inválido en corrección admin (Property 8 — admin)
    - **Feature: tournament-config-arrow-correction, Property 8: Rechazo de corrección de flecha con arrow_val inválido (admin)**
    - Igual al test 4.4 pero para `correct_arrow_admin()`; verificar error con `field='arrow_val'` y sin modificación
    - **Validates: Requirement 4.3**

- [ ] 6. Archer_Module — `get_accumulated_points()` y property de invariante de puntos
  - [ ]* 6.1 Escribir property test — invariante de puntos acumulados (Property 11)
    - **Feature: tournament-config-arrow-correction, Property 11: Invariante de puntos acumulados tras correcciones**
    - Insertar N flechas, aplicar M correcciones aleatorias; verificar que `get_accumulated_points()` retorna exactamente la suma aritmética de los `points` actuales en la BD
    - **Validates: Requirement 6.3**

- [x] 7. Archer Routes — actualizar `score_post()` para usar configuración del torneo
  - [x] 7.1 Modificar `score_post()` en `archer/routes/archer_routes.py`
    - Reemplazar el uso de `ARROWS_PER_END` y `ENDS_PER_ROUND` por `tournament["arrows_per_end"]` y `tournament["rounds"]`
    - Usar `arrows_per_end = tournament["arrows_per_end"]` y `ends_per_round = tournament["rounds"]` como variables locales
    - Mantener la misma lógica de rollover: si `end_number >= ends_per_round` → `session["round_number"] += 1`, `session["end_number"] = 1`; si no → `session["end_number"] += 1`
    - Pasar `arrows_per_end` y `ends_per_round` al template de score para que muestre el progreso correctamente
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ]* 7.2 Escribir property test — progresión de tanda basada en configuración (Property 4)
    - **Feature: tournament-config-arrow-correction, Property 4: Progresión de tanda basada en configuración del torneo**
    - `@given(arrows_per_end=st.integers(1,12))`; crear torneo con ese `arrows_per_end`, guardar exactamente `arrows_per_end` flechas vía test client, verificar que `end_number` avanzó
    - **Validates: Requirements 2.1, 2.4**

  - [ ]* 7.3 Escribir property test — rollover de ronda basado en configuración (Property 5)
    - **Feature: tournament-config-arrow-correction, Property 5: Rollover de ronda basado en configuración del torneo**
    - `@given(rounds=st.integers(1,20))`; completar la última tanda de la ronda, verificar `round_number += 1` y `end_number = 1`
    - **Validates: Requirement 2.2**

- [x] 8. Archer Routes — añadir ruta `POST /archer/score/correct`
  - [x] 8.1 Implementar `correct_arrow()` en `archer/routes/archer_routes.py`
    - Decorar con `@require_session` (o el decorador de sesión activo en el proyecto)
    - Leer `score_id` y `arrow_val` del form
    - Obtener `archer_id`, `round_number`, `end_number` de la sesión y `tournament["id"]` de `get_active_tournament()`
    - Llamar a `correct_arrow_archer(...)` y manejar errores: si `"error"` en resultado → re-renderizar score con error, status del resultado
    - En éxito: actualizar `session["last_active"]`, redirect a `url_for("archer.score")`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 9. Admin Routes — actualizar `POST /admin/tournaments` y añadir ruta de corrección
  - [x] 9.1 Actualizar la ruta `POST /admin/tournaments` en `archer/routes/admin_routes.py`
    - Leer `rounds` y `arrows_per_end` del form y pasarlos a `create_tournament()`
    - Si el resultado contiene `"error"` con `field='rounds'` o `field='arrows_per_end'`, re-renderizar el template con el error correspondiente
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 9.2 Implementar ruta `POST /admin/scores/correct` en `archer/routes/admin_routes.py`
    - Decorar con `@require_admin`
    - Leer `score_id`, `arrow_val` y `redirect_to` del form (default `url_for("admin.tournaments")`)
    - Llamar a `correct_arrow_admin(score_id, arrow_val)` y manejar error → re-renderizar con error
    - En éxito: redirect a `redirect_to`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 10. Templates — panel de administración
  - [x] 10.1 Actualizar `templates/admin/tournaments.html`
    - Añadir campos `rounds` y `arrows_per_end` (tipo `number`, valores default 10 y 6) en el formulario de creación de torneo
    - Mostrar `rounds` y `arrows_per_end` en la fila de cada torneo en el listado
    - Mostrar mensajes de error inline para `field='rounds'` y `field='arrows_per_end'`
    - _Requirements: 1.5, 1.6_

  - [x] 10.2 Actualizar `templates/admin/enrolled_archers.html`
    - Añadir para cada flecha de cada arquero un formulario oculto/inline con `score_id`, `arrow_val` (selector de los 12 valores) y un botón "Corregir"
    - El form debe hacer `POST /admin/scores/correct` con `redirect_to` apuntando de vuelta a la página de arqueros inscritos
    - _Requirements: 4.5_

- [x] 11. Templates — teclado táctil del arquero
  - [x] 11.1 Actualizar `templates/archer/score.html`
    - En el resumen de la tanda activa, añadir junto a cada flecha un control de corrección: selector `arrow_val` + botón "Corregir" que hace `POST /archer/score/correct`
    - Mostrar el progreso usando los valores `arrows_per_end` y `ends_per_round` pasados desde la ruta
    - _Requirements: 3.5_

- [x] 12. Checkpoint final — todos los tests pasan
  - Ejecutar `pytest --tb=short` y asegurar que todos los tests (unitarios, propiedades y smoke) pasan. Consultar al usuario si surgen dudas.

---

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para una entrega más rápida
- Las constantes `ARROWS_PER_END` y `ENDS_PER_ROUND` se conservan en `archer.py` por retrocompatibilidad con tests existentes, pero dejan de usarse en la lógica de progresión de sesión
- La columna `rounds` en la tabla `tournaments` actúa como `ends_per_round` semánticamente; el naming se preserva para minimizar cambios en el esquema
- El mapeo canónico `arrow_val → points` es: `X`→10, `10`→10, `9`→9, …, `1`→1, `M`→0
- Los property tests usan `@settings(max_examples=100)` con SQLite `:memory:`
- El tag de cada property test sigue el formato: `# Feature: tournament-config-arrow-correction, Property N: texto`
- La corrección de flechas es una operación `UPDATE` atómica; no se requiere bloqueo adicional
- `broadcast_update()` debe llamarse tras cualquier corrección exitosa (arquero o admin)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "4.1", "5.1"] },
    { "id": 3, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "5.2", "5.3", "6.1", "7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "8.1", "9.1"] },
    { "id": 5, "tasks": ["9.2"] },
    { "id": 6, "tasks": ["10.1", "10.2", "11.1"] },
    { "id": 7, "tasks": ["12"] }
  ]
}
```
