# Directivas de Arquitectura e Infraestructura

- **Backend:** Python 3.12+ con Flask.
- **Base de Datos:** Turso (libSQL / SQLite Edge).
- **Conexión BD:** SDK `libsql-experimental` (o `sqlite3` para desarrollo local en fallback).
- **Frontend / UI:** HTML5, CSS accesible (Tailwind CSS via CDN) y JavaScript vanilla/Alpine.js para interactividad liviana en móvil.
- **Gráficos:** Chart.js (CDN) para tendencias y distribución de tiros.
- **Real-Time:** Server-Sent Events (SSE) con Flask para transmitir las actualizaciones del Leaderboard en vivo a los espectadores sin recargar.
- **Mobile First:** Teclado táctil con botones gigantes pensado para uso con pulgares en campo de tiro.