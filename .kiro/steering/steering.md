---
inclusion: always
---

# Proyecto: Mosca — Gestión de Torneos de Arquería

## Stack
- **Backend:** Python 3.12 + Flask (app factory en `archer/app.py`)
- **DB en producción:** Turso (libSQL) vía `turso-serverless==0.1.0`
- **DB en local:** SQLite (`/tmp/db.sqlite3` en Vercel, `db.sqlite3` en local)
- **Deploy:** Vercel — entrypoint `api/index.py` → `archer.app:app`
- **Dependencias:** `pyproject.toml` es la fuente de verdad para Vercel (uv). `requirements.txt` solo para dev local.
- **Frontend:** Jinja2 + Tailwind CSS CDN + Alpine.js + Chart.js

## Arquitectura

```
archer/
  app.py          — Application factory, blueprints, home route, /health
  config.py       — Config desde env vars
  db.py           — Conexión singleton (turso_serverless o sqlite3), init_db(), _DictRow
  modules/
    admin.py      — CRUD torneos, categorías, arqueros, inscripciones
    archer.py     — Login PIN, carga de puntajes
    club.py       — Branding del club (club_settings)
    news.py       — Noticias/ticker
    scoring.py    — Lógica de puntajes
    stats.py      — Estadísticas, ranking, archer_kpis(), archer_history(), archer_trend()
  routes/
    admin_routes.py       — Blueprint /admin (incluye tournament_detail con tabs)
    archer_routes.py      — Blueprint /archer (incluye /archer/dashboard)
    leaderboard_routes.py — Blueprint /leaderboard (SSE)
    stats_routes.py       — Blueprint /stats
  templates/
    admin/base_admin.html       — Layout con sidebar + navbar sólido (color_from) + Salir en sidebar
    admin/login.html            — Página standalone (sin sidebar, sin footer)
    admin/tournaments.html      — Lista torneos (modal+FAB)
    admin/tournament_detail.html — Detalle con tabs (Categorías/Arqueros/Acciones)
    admin/archers.html          — Lista arqueros (modal+FAB, inscripción colapsable)
    admin/news.html             — Gestor de noticias
    admin/club_settings.html    — Branding con preview sticky, presets color, sticky save bar
    admin/edit_archer.html      — Editar nombre y PIN
    admin/enrolled_archers.html — Arqueros de un torneo
    admin/categories.html       — Categorías (legacy)
    archer/login.html           — Teclado PIN táctil (extiende base.html, sin nav en header)
    archer/score.html           — Teclado de flechas + modal (standalone, sin base.html)
    archer/dashboard.html       — Dashboard personal: KPIs, banner torneo, historial, chart
    stats/ranking.html          — Ranking global con podio
    stats/tournament.html       — Estadísticas de torneo con gráfico
    stats/trend.html            — Historial de un arquero
    base.html                   — Layout público (sin footer, avatar/dropdown si archer_logged, bottom nav)
    home.html                   — Página standalone (drawer hamburguesa, banner descartable)
api/index.py      — Entrypoint Vercel
pyproject.toml    — Dependencias para Vercel (uv)
requirements.txt  — Dependencias para dev local
```

## Sistema de Diseño (Design System)

### Principios
- **Mobile-first:** botones grandes (mín. 44px), teclado táctil, FAB en móvil
- **Contenido sobre creación:** los listados son el elemento principal, los formularios van en modales
- **Minimalista:** sin textos de ayuda innecesarios, sin gradientes en navbar, sin footers
- **Sin footers:** ningún template tiene footer

### Layouts disponibles

#### `admin/base_admin.html` — Panel admin
- Navbar color sólido: `style="background-color: {{ club.color_from }}"` (sin gradiente)
- Sidebar con nav items y botón Salir al pie con ícono logout
- Sin footer
- Ítem activo: `bg-green-50 text-green-800` / hover: `hover:bg-gray-100`

#### `base.html` — Páginas públicas y del arquero
- Header con `background-color: {{ club.color_from }}`
- Si `session.archer_id`: avatar con dropdown (Mi Dashboard / Cargar flechas / Cerrar sesión)
- Si no hay sesión: botones Admin (tenue) + Ingresar PIN
- `{% block header_nav %}` sobreescribible para suprimir el nav (usado en `archer/login.html`)
- Bottom nav fija si hay `session.archer_id`: Inicio / Competencia / Historial
- Sin footer
- `pb-24` automático en `<main>` si hay bottom nav

#### `home.html` — Standalone (no extiende base.html)
- Tiene su propio header con hamburguesa
- Drawer lateral con: Inicio → Ranking → Leaderboard activo → Ingresar como Arquero (CTA) → Panel Admin (🔒)
- Banner de anuncio estático descartable (Alpine.js `bannerVisible`)
- Widget clima condicional: `x-show="ready"`, solo aparece si geolocalización funciona

#### `admin/login.html` — Standalone (no extiende nada)
- Página centrada, sin sidebar, sin footer

### Componentes reutilizables

#### Modal / Offcanvas (Alpine.js)
```html
<button @click="$dispatch('open-NOMBRE-modal')">...</button>

<div x-data="{ open: false }" @open-NOMBRE-modal.window="open = true"
     x-show="open" x-cloak class="fixed inset-0 z-50 flex items-end sm:items-center ...">
  <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" @click="open = false"></div>
  <div class="relative w-full sm:max-w-md bg-white rounded-t-3xl sm:rounded-2xl ..."
       x-transition:enter-start="translate-y-full sm:translate-y-4 opacity-0">
    <!-- Handle móvil -->
    <div class="flex justify-center pt-3 pb-1 sm:hidden">
      <div class="w-10 h-1.5 bg-gray-200 rounded-full"></div>
    </div>
  </div>
</div>
```

#### FAB (Floating Action Button)
```html
<button @click="$dispatch('open-NOMBRE-modal')"
        class="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full
               bg-green-700 text-white shadow-lg flex items-center justify-center
               transition-colors lg:hidden">
```

#### Stepper (Alpine.js) — para campos numéricos
```html
<div x-data="stepper(VALOR_INICIAL, MIN, MAX)"
     class="flex items-center border border-gray-200 rounded-xl overflow-hidden">
  <button type="button" @click="dec()" class="w-12 h-11 text-xl font-light select-none">−</button>
  <input type="number" name="CAMPO" :value="val" x-model="val"
         class="flex-1 text-center text-sm font-semibold border-0 focus:outline-none h-11" />
  <button type="button" @click="inc()" class="w-12 h-11 text-xl font-light select-none">+</button>
</div>
<script>
function stepper(initial, min, max) {
  return { val: parseInt(initial)||min, inc(){if(this.val<max)this.val++;}, dec(){if(this.val>min)this.val--;} };
}
</script>
```

#### Tabs (Alpine.js)
```html
<div x-data="{ tab: 'tab1' }">
  <div class="flex border-b border-gray-200 mb-5 gap-1">
    <button @click="tab = 'tab1'"
            :class="tab==='tab1' ? 'border-b-2 border-green-600 text-green-700 font-semibold' : 'text-gray-500'"
            class="px-4 py-2.5 text-sm transition-colors">Tab 1</button>
  </div>
  <div x-show="tab === 'tab1'" x-cloak>...</div>
</div>
```

#### Badge de estado del torneo
```html
<!-- En curso -->
<span class="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-green-100 text-green-700">
  <span class="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse inline-block"></span>En curso
</span>
<!-- Próximo (created) -->
<span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-50 text-blue-600">Próximo</span>
<!-- Finalizado -->
<span class="text-xs font-semibold px-2.5 py-1 rounded-full bg-gray-100 text-gray-500">Finalizado</span>
```

#### Input estándar
```html
<input class="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm
              focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent
              {% if field == 'campo' %}border-red-400 bg-red-50{% endif %}" />
```

#### Tarjeta de item en lista (clicable)
```html
<a href="..." class="block bg-white rounded-2xl shadow-sm border border-gray-100 p-4
                     hover:border-green-300 hover:shadow-md transition-all duration-150">
```

#### Botón primario
```html
<button class="bg-green-700 hover:bg-green-800 active:bg-green-900 text-white
               font-semibold px-5 py-2.5 rounded-xl text-sm transition-colors">
```

#### Estado vacío
```html
<div class="text-center py-16 text-gray-400">
  <div class="text-5xl mb-3">🎯</div>
  <p class="font-medium">Título del estado vacío</p>
  <p class="text-sm mt-1">Descripción de la acción a tomar</p>
</div>
```

#### Formateo de fechas en Jinja2
```jinja2
{% set meses = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'] %}
{% set partes = t.date.split('-') if t.date else [] %}
{% set fecha_legible = (partes[2]|int)|string + ' ' + meses[(partes[1]|int) - 1] + ', ' + partes[0] if partes|length == 3 else t.date %}
```

---

## Conexión a Base de Datos (`archer/db.py`)

- `turso_serverless` se importa a nivel de módulo (no lazy)
- `_DictRow` es el row_factory para Turso: soporta `dict(row)`, `row['col']` y `row[0]`
- `sqlite3.Row` para conexiones locales
- Singleton en `current_app.config["DB_CONN"]`
- `init_db()` crea tablas al primer request via `@app.before_request`
- `logging.basicConfig(force=True)` en `db.py` para capturar logs en Vercel

## Variables de Entorno (Vercel)

| Variable | Descripción |
|---|---|
| `TURSO_DATABASE_URL` | `libsql://mosca-fcampo92.aws-us-east-1.turso.io` |
| `TURSO_AUTH_TOKEN` | Token JWT de Turso |
| `SESSION_SECRET` | Secret para Flask sessions |
| `ADMIN_USERNAME` | Usuario admin (default: admin) |
| `ADMIN_PASSWORD` | Contraseña admin |
| `CLOUDINARY_URL` | Para subida de fotos de arqueros |

## Decisiones Técnicas Clave

1. **`pyproject.toml` es la fuente de verdad para Vercel** — uv lo lee e ignora `requirements.txt`
2. **`turso-serverless` en lugar de `libsql-experimental`** — HTTP puro, sin conexiones persistentes
3. **`_DictRow` row_factory** — `turso_serverless.Row.__iter__` itera valores (no key-value). `_DictRow(dict)` resuelve soportando los tres modos de acceso
4. **Logging root con `basicConfig(force=True)`** — Flask sobreescribe handlers; `force=True` garantiza captura en Vercel
5. **Vista detalle de torneo** — `/admin/tournaments/<id>` con tabs reemplaza botones separados
6. **Dashboard del arquero** — `/archer/dashboard` con `archer_kpis()` y `archer_history()` en `stats.py`
7. **`home.html` standalone** — no extiende `base.html` porque tiene su propio drawer y lógica de sesión dual (arquero/público)
8. **`archer/score.html` standalone** — layout full-screen sin header/footer para la pantalla de tiro

## Schema de Base de Datos

```sql
archers        (id, pin, name, photo_url, created_at)
tournaments    (id, name, date, status, rounds, arrows_per_end, rounds_count, created_at)
categories     (id, tournament_id, bow_type, distance, gender)
registrations  (id, tournament_id, archer_id, category_id)
scores         (id, tournament_id, archer_id, round_number, end_number, arrow_val, points, created_at)
news           (id, title, content, active, created_at)
club_settings  (id, club_name, hero_title, hero_subtitle, ticker_text, color_from, color_to, updated_at)
```

## Estado Actual del Proyecto

- Deploy en Vercel funcionando: `mosca-bice.vercel.app`
- Turso conectado con `_DictRow` row_factory
- UI completamente modernizada con design system consistente
- Último commit: `c7295fe` — fix: quitar footer de base.html, block header_nav para login del arquero
