# Bugfix Requirements Document

## Introduction

Este documento cubre seis problemas críticos identificados en la app KiroArchery (Flask + Turso/SQLite). El análisis del código reveló las causas raíz de cada bug: el sistema de registro de puntos pierde flechas por un bug en el avance de tanda; el panel admin es completamente público sin ningún mecanismo de autenticación; no existe forma de limpiar datos de prueba; la vista de torneos existentes carece de accesos directos clave; no hay opción de eliminar torneos; y el portal de estadísticas personales del arquero no está accesible desde su sesión activa.

---

## Bug Analysis

### Bug 1 — Registro de puntos no avanza de tanda correctamente

**Causa raíz identificada en el código:** En `archer_routes.py`, `score_post()` redirige vía PRG (`redirect(url_for("archer.score"))`) tras guardar cada flecha, pero nunca incrementa `session["end_number"]` ni `session["round_number"]`. Los valores permanecen siempre en `1` durante la sesión. Así, todas las flechas se persisten bajo `end_number=1, round_number=1`, lo que hace que `get_end_summary()` muestre siempre el mismo acumulado creciente de la tanda 1 en lugar de mostrar la tanda en curso. El arquero no puede avanzar de tanda ni de ronda manualmente.

---

### Bug 2 — Panel admin sin autenticación

**Causa raíz identificada en el código:** El blueprint `/admin` en `admin_routes.py` no tiene ningún decorador de autenticación, middleware, ni verificación de sesión en ninguna de sus rutas. `base.html` incluye links directos a `/admin/tournaments` y `/admin/archers` en el `<nav>` sin ninguna restricción. Cualquier persona con la URL puede crear torneos, crear arqueros, inscribir arqueros y cambiar estados de torneos.

---

### Bug 3 — Sin mecanismo de limpieza/reset de datos de prueba

**Causa raíz identificada en el código:** No existe ninguna ruta, endpoint ni función en `admin_routes.py` ni en `admin.py` que permita eliminar o resetear datos. Las tablas `archers`, `tournaments`, `categories`, `registrations` y `scores` solo pueden vaciarse con acceso directo a la base de datos. No hay ningún botón ni confirmación de "reset" en la UI.

---

### Bug 4 — UX/UI de torneos existentes sin accesos clave

**Causa raíz identificada en el código:** En `admin/tournaments.html`, la tarjeta de cada torneo solo muestra el botón "Categorías" y los botones de cambio de estado. Faltan accesos directos a: ver las inscripciones/arqueros del torneo, ver el leaderboard en vivo, y ver las estadísticas del torneo. El Organizador debe navegar manualmente a `/leaderboard/{id}` o `/stats/tournament/{id}/view` escribiendo la URL.

---

### Bug 5 — Sin opción de eliminar torneos

**Causa raíz identificada en el código:** `admin_routes.py` no tiene ninguna ruta `DELETE` ni `POST` para eliminar torneos. `admin.py` tampoco expone ninguna función `delete_tournament()`. La UI `tournaments.html` no incluye ningún botón de eliminación.

---

### Bug 6 — Portal de estadísticas personales no accesible para arqueros

**Causa raíz identificada en el código:** `stats_routes.py` expone `/stats/archer/<archer_id>/trend/view` y `/stats/tournament/<tournament_id>/view`, pero estas rutas requieren conocer el `archer_id` (UUID) o `tournament_id` de antemano y no tienen ningún link desde la sesión del arquero. `score.html` no incluye ningún acceso a estadísticas propias. Además, `stats_routes.py` no protege ninguna de sus rutas con verificación de sesión, por lo que cualquiera puede acceder a los datos de cualquier arquero si conoce su UUID. No existe un dashboard centralizado que un arquero autenticado pueda visitar para ver sus propias estadísticas.

---

### Current Behavior (Defect)

1.1 WHEN un arquero autenticado registra su sexta flecha o más en una sesión, THEN el sistema persiste todas las flechas bajo `round_number=1, end_number=1` sin incrementar la tanda ni la ronda

1.2 WHEN un arquero registra flechas, THEN el sistema muestra siempre el resumen de la tanda 1 acumulando todas las flechas, en lugar de mostrar la tanda actual

1.3 WHEN cualquier usuario no autenticado accede a `/admin/tournaments`, `/admin/archers` o `/admin/tournaments/<id>/categories`, THEN el sistema muestra el panel de administración completo sin solicitar credenciales

1.4 WHEN un usuario no autorizado envía un POST a `/admin/tournaments` o `/admin/archers/<id>/enroll`, THEN el sistema ejecuta la operación y persiste los cambios en la base de datos

1.5 WHEN el organizador quiere eliminar datos de prueba de arqueros o torneos, THEN el sistema no ofrece ningún mecanismo de limpieza, forzando acceso directo a la base de datos

1.6 WHEN el organizador ve la lista de torneos, THEN el sistema no muestra accesos directos al leaderboard en vivo, a las estadísticas del torneo ni a los arqueros inscritos

1.7 WHEN el organizador quiere eliminar un torneo, THEN el sistema no presenta ningún botón ni ruta para eliminarlo

1.8 WHEN un arquero con sesión activa quiere ver sus propias estadísticas y tendencia histórica, THEN el sistema no ofrece ningún acceso desde la pantalla de score ni desde ninguna vista autenticada del arquero

1.9 WHEN el admin accede a `/stats/archer/<archer_id>/trend/view` para ver las estadísticas de otro arquero, THEN el sistema no verifica si el solicitante tiene permisos para ver esos datos

---

### Expected Behavior (Correct)

2.1 WHEN un arquero registra flechas y completa una tanda (ej. 6 flechas), THEN el sistema SHALL avanzar automáticamente `end_number` en la sesión y presentar la siguiente tanda en blanco

2.2 WHEN un arquero está en una tanda, THEN el sistema SHALL mostrar únicamente las flechas de la tanda actual basándose en `round_number` y `end_number` correctos de la sesión

2.3 WHEN un usuario no autenticado intenta acceder a cualquier ruta bajo `/admin/`, THEN el sistema SHALL redirigirlo al formulario de login de admin y no revelar ningún contenido protegido

2.4 WHEN un usuario envía credenciales correctas de admin (usuario + contraseña), THEN el sistema SHALL crear una sesión de admin, registrar el evento en el log y redirigir al panel de torneos

2.5 WHEN un usuario envía credenciales incorrectas de admin, THEN el sistema SHALL rechazar el acceso, mostrar un mensaje de error genérico y registrar el intento fallido

2.6 WHEN el organizador autenticado accede a la vista de torneos, THEN el sistema SHALL mostrar un botón de acceso directo al leaderboard en vivo para torneos con estado `active` y un botón de estadísticas para torneos con estado `finished`

2.7 WHEN el organizador autenticado accede a la vista de torneos, THEN el sistema SHALL mostrar un botón para ver los arqueros inscritos en cada torneo

2.8 WHEN el organizador autenticado hace clic en "Eliminar" en un torneo con estado `created`, THEN el sistema SHALL solicitar confirmación, y al confirmar, eliminar el torneo y sus categorías asociadas de la base de datos

2.9 WHEN el organizador autenticado solicita resetear datos de prueba, THEN el sistema SHALL permitir eliminar individualmente arqueros sin inscripciones activas en torneos `active` o `finished`

2.10 WHEN un arquero con sesión activa accede a su panel de score, THEN el sistema SHALL mostrar un acceso a sus estadísticas personales (tendencia histórica y estadísticas de torneos en los que participó)

2.11 WHEN un arquero autenticado accede a su portal de estadísticas, THEN el sistema SHALL mostrar únicamente sus propios datos sin exponer datos de otros arqueros

2.12 WHEN el organizador admin autenticado accede al portal de estadísticas, THEN el sistema SHALL mostrar las estadísticas de todos los arqueros con capacidad de filtrar por arquero

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN un arquero autenticado registra una flecha en un torneo `active`, THEN el sistema SHALL CONTINUE TO persistir la flecha con `arrow_val` y `points` correctos en la tabla `scores`

3.2 WHEN un arquero autenticado registra una flecha, THEN el sistema SHALL CONTINUE TO actualizar el contador de puntos acumulados correctamente

3.3 WHEN un arquero ingresa su PIN de 4 dígitos correcto, THEN el sistema SHALL CONTINUE TO autenticarlo y redirigirlo a la pantalla de score

3.4 WHEN un arquero realiza 5 intentos fallidos consecutivos, THEN el sistema SHALL CONTINUE TO bloquear el PIN durante 5 minutos

3.5 WHEN el organizador crea un torneo con nombre válido y fecha en formato `YYYY-MM-DD`, THEN el sistema SHALL CONTINUE TO crear el torneo con estado `created` y UUID v4

3.6 WHEN el organizador cambia el estado de un torneo siguiendo las transiciones válidas (`created→active`, `active→finished`), THEN el sistema SHALL CONTINUE TO actualizar el estado correctamente

3.7 WHEN el organizador crea una categoría con combinación única de `bow_type`, `distance` y `gender` para un torneo, THEN el sistema SHALL CONTINUE TO persistir la categoría

3.8 WHEN el leaderboard recibe una actualización tras una flecha registrada, THEN el sistema SHALL CONTINUE TO emitir el evento SSE en ≤ 2 segundos

3.9 WHEN un cliente se conecta al endpoint SSE, THEN el sistema SHALL CONTINUE TO enviar el estado completo del leaderboard como primer evento

3.10 WHEN el organizador solicita el ranking global, THEN el sistema SHALL CONTINUE TO retornar únicamente puntos de torneos con estado `finished` ordenados por `total_points DESC` y `name ASC`

3.11 WHEN un arquero no tiene sesión activa e intenta acceder a `/archer/score`, THEN el sistema SHALL CONTINUE TO redirigirlo al formulario de login de PIN

---

## Bug Condition Pseudocode

### Bug 1 — Avance de tanda

```pascal
FUNCTION isBugCondition_TandaNoAvanza(request)
  INPUT: request POST a /archer/score
  OUTPUT: boolean
  
  RETURN session["end_number"] REMAINS UNCHANGED after save_arrow() success
END FUNCTION

// Property: Fix Checking
FOR ALL request WHERE isBugCondition_TandaNoAvanza(request) DO
  result ← score_post'(request)
  ASSERT session["end_number"] = previous_end_number + 1 (si se completó la tanda)
  OR session["round_number"] = previous_round_number + 1 (si se completó la ronda)
END FOR

// Property: Preservation Checking
FOR ALL request WHERE NOT isBugCondition_TandaNoAvanza(request) DO
  ASSERT save_arrow'(request) = save_arrow(request)  // persistencia sin cambios
END FOR
```

### Bug 2 — Admin sin auth

```pascal
FUNCTION isBugCondition_AdminSinAuth(request)
  INPUT: request HTTP a /admin/*
  OUTPUT: boolean
  
  RETURN "admin_session" NOT IN request.session
END FUNCTION

// Property: Fix Checking
FOR ALL request WHERE isBugCondition_AdminSinAuth(request) DO
  result ← admin_view'(request)
  ASSERT result.status_code = 302 AND result.location = "/admin/login"
END FOR
```
