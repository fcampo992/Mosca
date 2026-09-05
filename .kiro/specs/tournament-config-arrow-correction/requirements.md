# Requirements Document

## Introduction

Este documento especifica los requerimientos para dos nuevas funcionalidades del sistema de torneos de arquería (Archer App):

1. **Configuración de rondas y flechas por torneo**: El administrador puede definir cuántas rondas tiene un torneo y cuántas flechas se lanzan por tanda (`end`), en lugar de depender de los valores hardcodeados `ENDS_PER_ROUND = 10` y `ARROWS_PER_END = 6`.

2. **Corrección de flechas por el arquero**: El arquero puede corregir (modificar el valor de) una flecha que ya anotó en la tanda actual, siempre que la ronda todavía no haya sido confirmada. Una vez confirmada la ronda, solo un administrador puede hacer correcciones.

Estas funcionalidades impactan el esquema de base de datos (tabla `tournaments`), el módulo de administración (`admin.py`), el módulo del arquero (`archer.py`), las rutas correspondientes y los templates HTML.

---

## Glossary

- **Tournament_Config_System**: El subsistema de configuración de parámetros de torneo (rondas y flechas por tanda).
- **Arrow_Correction_System**: El subsistema que gestiona la corrección de flechas por parte del arquero o del administrador.
- **Admin_Module**: Módulo `archer/modules/admin.py` que gestiona torneos, categorías y arqueros.
- **Archer_Module**: Módulo `archer/modules/archer.py` que gestiona autenticación y puntuaciones.
- **Admin_Routes**: Blueprint Flask en `archer/routes/admin_routes.py`.
- **Archer_Routes**: Blueprint Flask en `archer/routes/archer_routes.py`.
- **Tournament**: Entidad de la tabla `tournaments` que representa un evento de competencia de arquería.
- **Round**: Unidad de competencia compuesta por un número configurable de tandas (`ends`).
- **End**: Tanda de flechas dentro de una ronda; su cantidad por ronda es configurable por torneo.
- **Arrow**: Flecha individual registrada en la tabla `scores` con un valor (`X`, `10`–`1`, `M`) y sus puntos equivalentes.
- **Confirmed_Round**: Ronda cuyas tandas han sido completamente cargadas y la sesión del arquero avanzó más allá del último `end` de esa ronda.
- **Active_End**: La tanda que el arquero está cargando actualmente (la que contiene `round_number` y `end_number` de su sesión en curso).
- **PIN**: Código numérico de 4 dígitos que identifica a un arquero.

---

## Requirements

### Requirement 1: Configuración de rondas al crear o editar un torneo

**User Story:** As an administrator, I want to configure the number of rounds and arrows per end when creating or editing a tournament, so that different tournament formats (indoor 18m, outdoor 70m, etc.) can be supported without modifying the source code.

#### Acceptance Criteria

1. WHEN an administrator creates a tournament, THE Tournament_Config_System SHALL persist the values `rounds` (number of rounds) and `arrows_per_end` (arrows per end) provided in the creation form together with the tournament record.

2. WHEN an administrator creates a tournament without providing `rounds` or `arrows_per_end`, THE Tournament_Config_System SHALL use the default values `rounds = 10` and `arrows_per_end = 6`.

3. THE Tournament_Config_System SHALL reject `rounds` values outside the range 1–20 (inclusive) and return a descriptive error with `field='rounds'`.

4. THE Tournament_Config_System SHALL reject `arrows_per_end` values outside the range 1–12 (inclusive) and return a descriptive error with `field='arrows_per_end'`.

5. WHEN the administration panel displays the tournament creation form, THE Admin_Routes SHALL render input fields for `rounds` and `arrows_per_end` with their default values pre-populated.

6. WHEN the administration panel displays the list of tournaments, THE Admin_Routes SHALL include the `rounds` and `arrows_per_end` values of each tournament in the rendered HTML.

---

### Requirement 2: Uso de la configuración del torneo para determinar el avance de tanda y ronda

**User Story:** As an archer, I want the score entry screen to advance to the next end or round based on the actual tournament configuration, so that I don't have to manually manage progression.

#### Acceptance Criteria

1. WHEN an archer saves an arrow and the total arrows in the current end reaches `tournament.arrows_per_end`, THE Archer_Module SHALL advance the session `end_number` to the next end (or roll over to `round_number + 1`, `end_number = 1` if the current end is the last one in the round).

2. WHEN the session `end_number` would exceed `tournament.ends_per_round` after an advance, THE Archer_Routes SHALL increment `session["round_number"]` by 1 and reset `session["end_number"]` to 1.

3. WHILE an archer is in an active tournament, THE Archer_Routes SHALL pass `tournament.arrows_per_end` and `tournament.ends_per_round` to the score template so the UI can display progress correctly.

4. THE Archer_Module SHALL read `arrows_per_end` and `ends_per_round` from the `tournaments` table record, instead of using the module-level constants `ARROWS_PER_END` and `ENDS_PER_ROUND`.

---

### Requirement 3: Corrección de una flecha por el arquero en la tanda activa

**User Story:** As an archer, I want to correct the value of an arrow I already entered in the current end, before confirming the round, so that I can fix mistakes made during score entry.

#### Acceptance Criteria

1. WHEN an archer requests to correct an arrow that belongs to the Active_End (identified by `score_id`, `round_number`, `end_number` matching the session's current position), THE Arrow_Correction_System SHALL update the `arrow_val` and `points` fields of that score record and return the updated record.

2. WHEN an archer requests to correct an arrow that belongs to a Confirmed_Round (i.e., `round_number` is less than the current session `round_number`, or `end_number` is less than the current session `end_number` within the same round), THE Arrow_Correction_System SHALL reject the request and return an error indicating that only an administrator can correct confirmed rounds.

3. WHEN an archer requests to correct an arrow with an invalid `arrow_val` (not in `["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"]`), THE Arrow_Correction_System SHALL reject the request and return a descriptive error with `field='arrow_val'`.

4. WHEN an archer requests to correct an arrow whose `score_id` does not belong to the archer's `archer_id` and `tournament_id`, THE Arrow_Correction_System SHALL reject the request and return an error with HTTP status 403.

5. WHEN the score entry screen displays the Active_End summary, THE Archer_Routes SHALL render a correction button or control next to each arrow in the current end summary, enabling the archer to trigger the correction flow inline.

6. IF the correction of an arrow succeeds, THEN THE Arrow_Correction_System SHALL trigger a leaderboard broadcast update for the affected `tournament_id`.

---

### Requirement 4: Corrección de una flecha por el administrador en cualquier ronda

**User Story:** As an administrator, I want to correct the value of any arrow in any round of a tournament, including confirmed rounds, so that I can fix errors that archers cannot self-correct.

#### Acceptance Criteria

1. WHEN an administrator requests to correct an arrow by `score_id` with a valid `arrow_val`, THE Arrow_Correction_System SHALL update the `arrow_val` and `points` fields of that score record regardless of which round or end it belongs to.

2. WHEN an administrator requests to correct an arrow with a `score_id` that does not exist in the `scores` table, THE Arrow_Correction_System SHALL return an error with HTTP status 404.

3. WHEN an administrator requests to correct an arrow with an invalid `arrow_val`, THE Arrow_Correction_System SHALL reject the request and return a descriptive error with `field='arrow_val'`.

4. IF the administrator correction succeeds, THEN THE Arrow_Correction_System SHALL trigger a leaderboard broadcast update for the affected `tournament_id`.

5. WHEN the administration panel displays the enrolled archers page for an active tournament, THE Admin_Routes SHALL provide a way for the administrator to view and correct individual arrows for each archer.

---

### Requirement 5: Integridad de datos del esquema de base de datos

**User Story:** As a developer, I want the database schema to store tournament configuration alongside the tournament record, so that configuration is always consistent with the scores stored for that tournament.

#### Acceptance Criteria

1. THE Tournament_Config_System SHALL add the columns `rounds` (INTEGER NOT NULL DEFAULT 10) and `arrows_per_end` (INTEGER NOT NULL DEFAULT 6) to the `tournaments` table via a migration or schema update in `init_db()`.

2. WHEN `init_db()` is called on a database that already has the `tournaments` table without the new columns, THE Tournament_Config_System SHALL add the columns without data loss (using `ALTER TABLE ... ADD COLUMN` with defaults).

3. FOR ALL existing tournament records after migration, THE Tournament_Config_System SHALL ensure `rounds = 10` and `arrows_per_end = 6` so that behavior is backwards-compatible with tournaments created before this feature was introduced.

---

### Requirement 6: Corrección de flechas — propiedad de round-trip y coherencia de puntos

**User Story:** As a developer, I want arrow corrections to consistently update the derived `points` field, so that leaderboard and statistics calculations remain correct after any correction.

#### Acceptance Criteria

1. FOR ALL valid `arrow_val` values in `["X", "10", "9", "8", "7", "6", "5", "4", "3", "2", "1", "M"]`, WHEN a correction is applied, THE Arrow_Correction_System SHALL set `points` to the value defined by the mapping `X→10, 10→10, 9→9, …, 1→1, M→0`, preserving the existing arrow-to-points invariant.

2. WHEN an arrow correction is applied and then the same arrow is corrected again to its original value, THE Arrow_Correction_System SHALL produce a score record identical to the state before the first correction (round-trip property).

3. WHEN `get_accumulated_points(archer_id, tournament_id)` is called after any number of corrections, THE Archer_Module SHALL return the arithmetic sum of the current `points` values of all score records for that archer in that tournament, reflecting all corrections.
