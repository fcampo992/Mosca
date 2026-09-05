# Implementation Plan: KiroArchery

## Overview

Implementación incremental de KiroArchery: una aplicación web Flask mobile-first para gestión de torneos de arquería en tiempo real. El plan sigue el orden natural de dependencias: infraestructura → módulos de negocio → rutas/blueprints → UI → SSE en tiempo real → estadísticas. Cada tarea construye sobre la anterior y termina con integración completa.

**Stack:** Python 3.12+ · Flask · Turso (libsql-experimental / sqlite3 fallback) · Jinja2 · Alpine.js · Tailwind CSS CDN · Chart.js CDN · SSE · pytest + Hypothesis

---

## Tasks

- [x] 1. Estructura de proyecto e infraestructura base
  - Crear el árbol de directorios: `archer/`, `archer/modules/`, `archer/routes/`, `archer/templates/` (con subdirectorios `admin/`, `archer/`, `leaderboard/`, `stats/`), `archer/static/`, `tests/unit/`, `tests/integration/`, `tests/smoke/`
  - Crear `requirements.txt` con versiones fijadas: `flask`, `libsql-experimental`, `hypothesis`, `pytest`, `pytest-flask`
  - Crear `archer/config.py` que lea `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` y `SESSION_SECRET` desde variables de entorno
  - Crear `archer/app.py` con la factory `create_app()`: registra blueprints, inicializa DB, configura `SESSION_SECRET`
  - _Requerimientos: 1.1, 1.2, 1.3_

- [x] 2. DB_Module — conexión singleton e inicialización de tablas
  - [x] 2.1 Implementar `archer/db.py` con `get_connection()` y `init_db()`
    - `get_connection()` implementa patrón singleton en `app.config['DB_CONN']`
    - Intentar conexión Turso con timeout 10 s; si falla → log + `exit(1)`
    - Si las variables de entorno no están definidas → usar `sqlite3` con `db.sqlite3`
    - `init_db()` ejecuta los cinco `CREATE TABLE IF NOT EXISTS` del esquema
    - _Requerimientos: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x]* 2.2 Escribir property test para singleton de conexión (Property 1)
    - **Property 1: Singleton de conexión**
    - **Validates: Requerimiento 1.5**
    - Verificar que N invocaciones a `get_connection()` retornan la misma instancia (identidad de objeto)

  - [x]* 2.3 Escribir tests unitarios para `init_db()` y fallback SQLite
    - Test: tablas creadas correctamente en DB en memoria
    - Test: fallback a sqlite3 cuando variables Turso no están definidas
    - _Requerimientos: 1.2, 1.3_

- [x] 3. Admin_Module — gestión de torneos
  - [x] 3.1 Implementar funciones de torneos en `archer/modules/admin.py`
    - `create_tournament(name, date)`: valida longitud (1–150 chars) y formato `YYYY-MM-DD`, genera UUID v4, persiste con `status='created'`
    - `list_tournaments()`: retorna todos los torneos ordenados por `created_at` DESC
    - `change_tournament_status(tournament_id, new_status)`: valida máquina de estados (`created→active`, `active→finished`; rechaza el resto)
    - _Requerimientos: 2.1, 2.2, 2.6, 2.7, 2.8, 2.9_

  - [x]* 3.2 Escribir property test para creación de torneo con entradas válidas (Property 2)
    - **Property 2: Creación de torneo con entradas válidas**
    - **Validates: Requerimiento 2.1**
    - Generar nombres (1–150 chars) y fechas `YYYY-MM-DD` válidas; verificar `status='created'` y UUID v4

  - [x]* 3.3 Escribir property test para rechazo de torneos con entradas inválidas (Property 3)
    - **Property 3: Rechazo de torneos con entradas inválidas**
    - **Validates: Requerimiento 2.2**
    - Generar entradas inválidas (nombre vacío, >150 chars, fecha con formato incorrecto); verificar error y que no se crea registro

  - [x]* 3.4 Escribir property test para transiciones de estado inválidas (Property 6)
    - **Property 6: Transiciones de estado inválidas del torneo**
    - **Validates: Requerimiento 2.8**
    - Probar pares inválidos `(finished→created, finished→active, active→created)`; verificar error y que `status` no cambia

  - [ ]* 3.5 Escribir property test para ordenamiento de listado de torneos (Property 7)
    - **Property 7: Ordenamiento del listado de torneos**
    - **Validates: Requerimiento 2.9**
    - Con N torneos con distintos `created_at`, verificar que se retornan exactamente N, ordenados DESC

- [x] 4. Admin_Module — gestión de categorías
  - [x] 4.1 Implementar funciones de categorías en `archer/modules/admin.py`
    - `create_category(tournament_id, bow_type, distance, gender)`: verifica existencia del torneo, verifica unicidad `(tournament_id, bow_type, distance, gender)`, genera UUID v4, persiste
    - `list_categories(tournament_id)`: retorna categorías del torneo
    - _Requerimientos: 2.3, 2.4, 2.5_

  - [ ]* 4.2 Escribir property test para persistencia de categorías (Property 4)
    - **Property 4: Persistencia de categorías**
    - **Validates: Requerimiento 2.3**
    - Para toda combinación válida, verificar que la categoría es recuperable por su `id` con atributos correctos

  - [ ]* 4.3 Escribir property test para unicidad de categorías (Property 5)
    - **Property 5: Unicidad de categorías**
    - **Validates: Requerimiento 2.5**
    - Verificar que duplicar `(tournament_id, bow_type, distance, gender)` retorna error sin incrementar conteo

- [x] 5. Admin_Module — gestión de arqueros e inscripciones
  - [x] 5.1 Implementar funciones de arqueros en `archer/modules/admin.py`
    - `create_archer(name, pin)`: valida nombre (1–100 chars), PIN (exactamente 4 dígitos numéricos), unicidad de PIN, genera UUID v4, persiste
    - `list_archers()`: retorna todos los arqueros ordenados alfabéticamente ASC por nombre
    - `enroll_archer(archer_id, tournament_id, category_id)`: valida que torneo no esté `finished`, que `category_id` pertenezca al `tournament_id`, que no exista inscripción duplicada; crea registro en `registrations`
    - _Requerimientos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [ ]* 5.2 Escribir property test para creación de arquero con entradas válidas (Property 8)
    - **Property 8: Creación de arquero con entradas válidas**
    - **Validates: Requerimiento 3.1**
    - Generar nombres (1–100 chars) y PINs de 4 dígitos; verificar persistencia con UUID v4 válido

  - [ ]* 5.3 Escribir property test para rechazo de PIN con formato inválido en creación (Property 9)
    - **Property 9: Rechazo de PIN con formato inválido**
    - **Validates: Requerimiento 3.2**
    - PINs con longitud incorrecta, chars no numéricos o vacíos; verificar error y que no se crea registro

  - [ ]* 5.4 Escribir property test para unicidad de PIN (Property 10)
    - **Property 10: Unicidad de PIN**
    - **Validates: Requerimiento 3.4**
    - Verificar que reutilizar PIN existente retorna error sin incrementar conteo de arqueros

  - [ ]* 5.5 Escribir property test para inscripción válida de arquero (Property 11)
    - **Property 11: Inscripción válida de arquero en torneo**
    - **Validates: Requerimiento 3.5**
    - Para torneo `created` o `active` con categoría válida, verificar que se crea exactamente un registro en `registrations`

  - [ ]* 5.6 Escribir property test para unicidad de inscripción (Property 12)
    - **Property 12: Unicidad de inscripción**
    - **Validates: Requerimiento 3.8**
    - Reinscribir mismo arquero/categoría/torneo; verificar error sin incrementar conteo en `registrations`

  - [ ]* 5.7 Escribir property test para ordenamiento alfabético de arqueros (Property 13)
    - **Property 13: Ordenamiento alfabético del listado de arqueros**
    - **Validates: Requerimiento 3.9**
    - Con N arqueros con distintos nombres, verificar orden ASC por nombre

- [x] 6. Checkpoint — módulos Admin completos
  - Asegurarse de que todos los tests pasen. Consultar al usuario si surgen dudas.

- [x] 7. Archer_Module — autenticación PIN y sesiones
  - [x] 7.1 Implementar `archer/modules/archer.py` — autenticación y manejo de sesiones
    - `authenticate_pin(pin)`: formato de validación (4 dígitos) antes de consultar DB; retorna archer o `None`; error genérico si no existe
    - Bloqueo en memoria: `dict` `{pin: (intentos, timestamp_bloqueo)}`; bloquear tras 5 intentos fallidos durante 5 minutos
    - `get_active_tournament(archer_id)`: retorna torneo `active` en el que el arquero está inscrito, o `None`
    - Lógica de expiración de sesión: `last_active` + 30 minutos
    - _Requerimientos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 7.2 Escribir property test para autenticación con PIN válido (Property 14)
    - **Property 14: Autenticación con PIN válido**
    - **Validates: Requerimiento 4.1**
    - Para cualquier arquero registrado, verificar que `authenticate_pin()` retorna sesión con `archer_id` y `name` correctos

  - [ ]* 7.3 Escribir property test para rechazo de PIN no registrado (Property 15)
    - **Property 15: Rechazo de PIN no registrado**
    - **Validates: Requerimiento 4.2**
    - PINs de 4 dígitos no registrados; verificar error genérico sin datos de otros arqueros y sin sesión creada

  - [ ]* 7.4 Escribir property test para validez de sesión por tiempo de actividad (Property 16)
    - **Property 16: Validez de sesión por tiempo de actividad**
    - **Validates: Requerimiento 4.4**
    - Para cualquier `last_active`, verificar: válido si `≤ 30 min`, rechazado si `> 30 min`

  - [ ]* 7.5 Escribir property test para rechazo de PIN con formato inválido en autenticación (Property 17)
    - **Property 17: Rechazo de PIN con formato inválido en autenticación**
    - **Validates: Requerimiento 4.6**
    - PINs no numéricos o longitud distinta de 4; verificar rechazo sin consultar DB

- [x] 8. Archer_Module — carga de puntuaciones (score entry)
  - [x] 8.1 Implementar funciones de puntuación en `archer/modules/archer.py`
    - `save_arrow(archer_id, tournament_id, round_number, end_number, arrow_val)`: valida que torneo esté `active`, mapea `arrow_val → points` (`X`→10, `10`→10, `9–1`→9–1, `M`→0), genera UUID v4, persiste en `scores`
    - `get_end_summary(archer_id, tournament_id, round_number, end_number)`: retorna lista de flechas y subtotal de la tanda
    - `get_accumulated_points(archer_id, tournament_id)`: retorna suma de `points` de todas las flechas del arquero en el torneo
    - _Requerimientos: 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [ ]* 8.2 Escribir property test para corrección del mapeo flecha → puntos (Property 18)
    - **Property 18: Corrección del mapeo flecha → puntos**
    - **Validates: Requerimiento 5.2**
    - `st.sampled_from(["X","10","9","8","7","6","5","4","3","2","1","M"])`; verificar `arrow_val` y `points` persistidos

  - [ ]* 8.3 Escribir property test para invariante de puntos acumulados (Property 19)
    - **Property 19: Invariante de puntos acumulados**
    - **Validates: Requerimiento 5.7**
    - Con N flechas, verificar que `get_accumulated_points()` retorna exactamente la suma aritmética de `points`

- [x] 9. Leaderboard_Module — cálculo y broadcasting SSE
  - [x] 9.1 Implementar `archer/modules/leaderboard.py`
    - `compute_leaderboard(tournament_id)`: agrupa arqueros por categoría, ordena por `total_points DESC, x_count DESC, ten_count DESC`, incluye campos `position, name, total_points, x_count, ten_count`
    - `broadcast_update(tournament_id)`: encola señal en `queue.Queue` por torneo (llamado desde `save_arrow`)
    - `sse_stream(tournament_id)`: generador que consume la cola; emite evento `leaderboard` con datos completos; emite `heartbeat` cada 30 s; envía estado completo como primer evento al conectar
    - Integrar llamada a `broadcast_update()` al final de `save_arrow()` exitoso
    - _Requerimientos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 9.2 Escribir property test para ordenamiento y estructura del leaderboard (Property 20)
    - **Property 20: Ordenamiento y estructura del leaderboard**
    - **Validates: Requerimientos 6.3, 6.4**
    - Con M categorías y arqueros con puntajes arbitrarios, verificar agrupación, orden y campos requeridos

  - [ ]* 9.3 Escribir property test para estado inicial completo en conexión SSE (Property 21)
    - **Property 21: Estado inicial completo en conexión SSE**
    - **Validates: Requerimiento 6.6**
    - Al conectar al stream, verificar que el primer evento contiene leaderboard completo y correcto

- [x] 10. Stats_Module — estadísticas por torneo
  - [x] 10.1 Implementar `archer/modules/stats.py` — `tournament_stats()`
    - Calcular `avg_points_per_arrow = round(sum(points) / count, 2)` por arquero (0.00 si sin flechas)
    - Calcular `top_zone_percentage = round(count(X o 10) / total * 100, 2)` por arquero (0.00 si sin flechas)
    - Retornar serie de rondas `{round_number, total_points}` ordenada ASC por `round_number`
    - Aplicar filtro por `archer_id` si se suministra (arquero ve solo sus datos)
    - Retornar HTTP 404 si `tournament_id` no existe
    - _Requerimientos: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ]* 10.2 Escribir property test para promedio de puntos por flecha (Property 22)
    - **Property 22: Promedio de puntos por flecha en estadísticas de torneo**
    - **Validates: Requerimiento 7.1**
    - Con K flechas, verificar `avg = round(sum(points)/K, 2)`

  - [ ]* 10.3 Escribir property test para porcentaje de zona alta (Property 23)
    - **Property 23: Porcentaje de zona alta en estadísticas de torneo**
    - **Validates: Requerimiento 7.2**
    - Verificar `round(count(X o 10) / K * 100, 2)`

  - [ ]* 10.4 Escribir property test para ordenamiento de rondas (Property 24)
    - **Property 24: Ordenamiento de rondas en estadísticas de torneo**
    - **Validates: Requerimiento 7.3**
    - Verificar que la serie de rondas está ordenada ASC por `round_number`

  - [ ]* 10.5 Escribir property test para aislamiento de datos por arquero (Property 25)
    - **Property 25: Aislamiento de datos por arquero en estadísticas**
    - **Validates: Requerimientos 7.5, 7.7**
    - Con múltiples arqueros, verificar que `tournament_stats(archer_id=X)` retorna solo datos de X

- [x] 11. Stats_Module — tendencia histórica y ranking global
  - [x] 11.1 Implementar `archer/modules/stats.py` — `archer_trend()` y `global_ranking()`
    - `archer_trend(archer_id)`: promedio por torneo `finished`, ordenado ASC por fecha; incluir torneos con 0 flechas (promedio=0.00); arreglo vacío si sin torneos `finished`
    - `global_ranking()`: sum de puntos solo de torneos `finished`, ordenar por `total_points DESC, name ASC`; arqueros sin torneos `finished` con totales en cero; retornar HTTP 503 si DB no disponible
    - _Requerimientos: 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 11.2 Escribir property test para tendencia histórica — cálculo, formato y orden (Property 26)
    - **Property 26: Tendencia histórica — cálculo, formato y orden**
    - **Validates: Requerimientos 8.1, 8.2**
    - Verificar campos `tournament_name, date, avg_points_per_arrow`, cálculo correcto y orden ASC por fecha

  - [ ]* 11.3 Escribir property test para corrección del ranking global (Property 27)
    - **Property 27: Corrección del ranking global**
    - **Validates: Requerimiento 9.1**
    - Verificar `total_points`, `avg_points_per_arrow` y `tournaments_played` para cada arquero

  - [ ]* 11.4 Escribir property test para ordenamiento del ranking global (Property 28)
    - **Property 28: Ordenamiento del ranking global**
    - **Validates: Requerimiento 9.2**
    - Verificar `total_points DESC`, desempate por `name ASC`

  - [ ]* 11.5 Escribir property test para filtro de torneos finished en ranking global (Property 29)
    - **Property 29: Filtro de torneos finished en ranking global**
    - **Validates: Requerimiento 9.3**
    - Verificar que puntos de torneos `created` o `active` no contribuyen al ranking

- [x] 12. Checkpoint — módulos de negocio completos
  - Asegurarse de que todos los tests unitarios y de propiedad pasen. Consultar al usuario si surgen dudas.

- [x] 13. Blueprints y rutas Flask
  - [x] 13.1 Crear `archer/routes/admin_routes.py` — Blueprint `/admin`
    - `GET/POST /admin/tournaments` — listar y crear torneos
    - `POST /admin/tournaments/<id>/status` — cambiar estado
    - `GET/POST /admin/tournaments/<id>/categories` — listar y crear categorías
    - `GET/POST /admin/archers` — listar y crear arqueros
    - `POST /admin/archers/<id>/enroll` — inscribir arquero
    - _Requerimientos: 2.1–2.9, 3.1–3.9_

  - [x] 13.2 Crear `archer/routes/archer_routes.py` — Blueprint `/archer`
    - `GET/POST /archer/login` — formulario de PIN y autenticación
    - `POST /archer/logout` — invalidar sesión
    - `GET/POST /archer/score` — teclado táctil de carga de flechas (requiere sesión activa)
    - Decorador de sesión: verificar `last_active ≤ 30 min` en cada request autenticado
    - _Requerimientos: 4.1–4.7, 5.1–5.7_

  - [x] 13.3 Crear `archer/routes/leaderboard_routes.py` — Blueprint `/leaderboard`
    - `GET /leaderboard/<tournament_id>` — vista HTML del leaderboard
    - `GET /leaderboard/<tournament_id>/stream` — endpoint SSE público (sin auth)
    - _Requerimientos: 6.1–6.7_

  - [x] 13.4 Crear `archer/routes/stats_routes.py` — Blueprint `/stats`
    - `GET /stats/tournament/<tournament_id>` — estadísticas de torneo (JSON)
    - `GET /stats/archer/<archer_id>/trend` — tendencia histórica (JSON)
    - `GET /stats/ranking` — ranking global (JSON)
    - _Requerimientos: 7.1–7.7, 8.1–8.4, 9.1–9.6_

- [x] 14. Plantillas HTML — panel de administración
  - [x] 14.1 Crear `archer/templates/base.html`
    - Layout base con Tailwind CSS CDN, Alpine.js CDN, Chart.js CDN
    - Estructura mobile-first (breakpoint base 360px)
    - _Requerimientos: 10.1_

  - [x] 14.2 Crear plantillas del panel de administración
    - `admin/tournaments.html` — listado y formulario de creación de torneos; botones de cambio de estado
    - `admin/categories.html` — listado y formulario de categorías por torneo
    - `admin/archers.html` — listado de arqueros, formulario de creación e inscripción
    - _Requerimientos: 2.1–2.9, 3.1–3.9_

- [x] 15. Plantillas HTML — teclado táctil del arquero
  - [x] 15.1 Crear plantillas de autenticación y score entry del arquero
    - `archer/login.html` — campo PIN numérico de 4 dígitos, mensaje de error genérico, feedback de bloqueo
    - `archer/score.html` — teclado táctil: 12 botones (`X`, `10`, `9`…`1`, `M`) de mínimo 60×60 px, espaciado ≥ 8px; contador acumulado visible; resumen de tanda; degradación sin Alpine.js con `<button type="submit" name="arrow_val">`
    - Usar Alpine.js para actualización reactiva del contador y resumen sin recarga de página
    - _Requerimientos: 4.6, 5.1, 5.2, 5.3, 5.6, 5.7, 10.1, 10.2, 10.3, 10.5_

- [x] 16. Plantillas HTML — leaderboard y estadísticas
  - [x] 16.1 Crear `archer/templates/leaderboard/live.html`
    - Tabla de clasificación agrupada por categoría con columnas: posición, nombre, puntos totales, Xs, 10s
    - Conexión SSE con `EventSource`; actualización del DOM en cada evento `leaderboard`; reconexión automática del navegador; ignorar evento `heartbeat`
    - Indicador de estado de conexión SSE (conectado / reconectando)
    - _Requerimientos: 6.1–6.7_

  - [x] 16.2 Crear plantillas de estadísticas con Chart.js
    - `stats/tournament.html` — gráfico de barras de evolución por ronda y tabla de métricas por arquero (avg, top_zone_%)
    - `stats/trend.html` — gráfico de línea de tendencia histórica del arquero
    - `stats/ranking.html` — tabla de ranking global con posición, nombre, total puntos, promedio, torneos jugados
    - _Requerimientos: 7.1–7.7, 8.1–8.4, 9.1–9.6, 10.4_

- [x] 17. Tests de integración SSE y smoke tests
  - [x]* 17.1 Escribir tests de integración SSE (`tests/integration/test_sse.py`)
    - Test: cliente recibe estado inicial completo al conectar
    - Test: evento `leaderboard` emitido en ≤ 2 s tras `save_arrow()`
    - Test: evento `heartbeat` emitido cada 30 s
    - Test: múltiples clientes simultáneos sin degradación
    - _Requerimientos: 6.2, 6.5, 6.7_

  - [ ]* 17.2 Escribir smoke tests de endpoints (`tests/smoke/test_endpoints.py`)
    - Test: todos los endpoints responden con código 2xx/3xx en condición nominal
    - Test: CDN de Tailwind, Alpine.js y Chart.js referencian URL válidas en el HTML generado
    - Test: endpoint SSE retorna `Content-Type: text/event-stream`
    - Test: teclado táctil renderiza 12 botones en la plantilla de score
    - _Requerimientos: 6.1, 10.1, 10.2, 10.4_

- [x] 18. Integración final y wire-up completo
  - [x] 18.1 Registrar todos los blueprints en `create_app()` y verificar coherencia de rutas
    - Verificar que `save_arrow()` llama a `broadcast_update()` correctamente
    - Verificar que el decorador de sesión protege todas las rutas de arquero
    - Verificar que `init_db()` se llama en `create_app()` antes de registrar blueprints
    - Agregar manejo centralizado de errores: 404, 422, 429, 503 con JSON `{"error": "...", "field": "..."}`
    - _Requerimientos: 1.3, 4.4, 5.3, 6.2, 10.5_

  - [x] 18.2 Crear `conftest.py` con fixtures compartidos de pytest
    - Fixture `test_db`: SQLite `:memory:` con esquema inicializado
    - Fixture `app`: instancia Flask de test con DB en memoria
    - Fixture `active_tournament`, `authenticated_archer`, `enrolled_archer`
    - _Requerimientos: todos_

- [x] 19. Checkpoint final — todos los tests pasan
  - Ejecutar `pytest --tb=short` y asegurarse de que todos los tests (unitarios, propiedades, integración y smoke) pasan. Consultar al usuario si surgen dudas.

---

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para una entrega MVP más rápida
- Cada tarea referencia requerimientos específicos para trazabilidad completa
- Los tests de propiedad usan `@settings(max_examples=100)` como mínimo, con DB SQLite `:memory:` para velocidad
- Los tests de integración SSE levantan Flask en un `threading.Thread` interno
- La degradación sin Alpine.js se garantiza con `<form>` estático y `<button type="submit" name="arrow_val">`
- El bloqueo de PIN por intentos fallidos vive en memoria (se resetea con reinicio del proceso, comportamiento aceptable)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["2.2", "2.3", "3.1", "4.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "3.5", "4.2", "4.3", "5.1"] },
    { "id": 3, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "7.4", "7.5", "8.1"] },
    { "id": 5, "tasks": ["8.2", "8.3", "9.1"] },
    { "id": 6, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 7, "tasks": ["10.2", "10.3", "10.4", "10.5", "11.1"] },
    { "id": 8, "tasks": ["11.2", "11.3", "11.4", "11.5", "13.1", "13.2", "13.3", "13.4"] },
    { "id": 9, "tasks": ["14.1", "18.2"] },
    { "id": 10, "tasks": ["14.2", "15.1"] },
    { "id": 11, "tasks": ["16.1", "16.2"] },
    { "id": 12, "tasks": ["17.1", "17.2", "18.1"] }
  ]
}
```
