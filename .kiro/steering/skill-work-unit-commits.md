---
inclusion: auto
name: work-unit-commits
description: "Plan commits as reviewable work units. Trigger: implementation, commit splitting, preparing commits before a PR, keeping tests and docs with code."
---

## Cuándo se activa

Cuando se va a hacer un commit, split de cambios, o preparar un PR.

## Reglas del proyecto Mosca

| Regla | Requisito |
|-------|-----------|
| Commit por unidad de trabajo | Un commit = un comportamiento, fix, migración o docs entregable. |
| No commitear por tipo de archivo | No hacer un commit solo de templates, luego otro solo de routes. |
| Tests con el código | Si el fix tiene un test, van en el mismo commit. |
| Mensaje explica el resultado | El mensaje dice QUÉ cambia, no los archivos que se tocaron. |
| Historia legible | Un revisor debe entender por qué existe cada commit leyendo el diff. |

## Formato de commit para Mosca

```
<tipo>(<scope>): <descripción corta>
```

### Tipos permitidos

| Tipo | Cuándo usarlo |
|------|---------------|
| `feat` | Nueva funcionalidad (ruta, template, módulo) |
| `fix` | Corrección de bug |
| `ui` | Cambio solo de templates/CSS sin lógica |
| `refactor` | Reorganización sin cambio funcional |
| `db` | Cambios en schema o migraciones |
| `docs` | Steering, README, comentarios |
| `chore` | Dependencias, configuración Vercel/pyproject |

### Scopes relevantes

`admin`, `archer`, `training`, `profile`, `leaderboard`, `stats`, `db`, `home`, `base`

### Ejemplos buenos para este proyecto

```
feat(training): agregar modo libre con contador de volumen
fix(score): confirmar tanda envia array completo via /score/end
ui(profile): reducir avatar para evitar truncado del nombre
db(training): agregar tablas training_sessions y training_ends
chore(vercel): agregar turso-serverless a pyproject.toml
```

## Checklist antes de commitear

- [ ] El commit tiene un solo propósito claro
- [ ] El repo funciona después de aplicar solo este commit
- [ ] El mensaje explica el resultado, no la lista de archivos
- [ ] Si es un fix de bug, incluye la causa raíz en el mensaje o body
