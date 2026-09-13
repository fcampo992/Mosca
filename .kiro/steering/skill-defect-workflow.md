---
inclusion: auto
name: defect-workflow
description: "Trigger: bug, error, fix, 500, falla, no funciona, no carga, no aparece, issue, problema, error en consola. Workflow para diagnosticar y corregir defectos en Mosca."
---

## Cuándo se activa

Cuando se reporta un bug, error 500, comportamiento inesperado, o algo que "no funciona".

## Reglas de diagnóstico

1. **Leer antes de tocar** — leer el código relevante completo antes de proponer un fix. No asumir la causa.
2. **Reproducir primero** — entender en qué condición exacta falla (Vercel vs local, con sesión vs sin sesión, con Turso vs SQLite).
3. **Identificar la causa raíz** — no el síntoma. Si el 500 es por un `None` en la DB, el fix es en la query, no en el try/except que lo tapa.
4. **Fix mínimo** — cambiar solo lo necesario para corregir el defecto. No refactorear alrededor.
5. **Verificar localmente** — `python -c "from archer.app import app; print('OK')"` antes de commitear.

## Checklist de fix

- [ ] ¿Leí el código que falla antes de editar?
- [ ] ¿Sé exactamente en qué condición se reproduce?
- [ ] ¿El fix ataca la causa raíz, no el síntoma?
- [ ] ¿Probé que el servidor levanta sin errores?
- [ ] ¿El mensaje del commit dice la causa raíz?

## Causas comunes en Mosca / Vercel

| Síntoma | Causa raíz frecuente |
|---------|---------------------|
| 500 en cualquier ruta | `get_connection()` falla — Turso timeout o token expirado |
| `[object Object]` en UI | `x-model` de Alpine sobre input que no es string puro |
| Foto no sube | `CLOUDINARY_URL` no configurada en Vercel env vars |
| Inscripción redirige mal | `redirect_to` faltante en el form |
| Race condition al anotar flechas | Fetch async múltiple — solución: acumular en Alpine, enviar todo junto |
| `dict(row)` con índices numéricos | `turso_serverless.Row.__iter__` itera valores — usar `_DictRow` |

## Formato del commit de fix

```
fix(<scope>): <descripción de lo que se corrige>

Causa: <causa raíz en una línea>
```

Ejemplo:
```
fix(score): confirmar tanda no avanzaba con flechas completas

Causa: doSubmit() referenciaba form=getElementById('score-form') que ya no existía
```
