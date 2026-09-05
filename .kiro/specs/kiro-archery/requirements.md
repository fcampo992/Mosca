# Documento de Requerimientos — KiroArchery

## Introducción

KiroArchery es una aplicación web responsiva (mobile-first) construida con Flask y Turso (SQLite Edge) que gestiona torneos de arquería en tiempo real. El sistema permite a organizadores crear torneos y categorías, registrar arqueros con PIN, controlar el estado del torneo y visualizar un leaderboard en vivo. Los arqueros cargan sus flechas desde sus celulares mediante un teclado táctil de botones grandes. La plataforma también genera estadísticas analíticas históricas por arquero y por torneo.

---

## Glosario

- **Sistema**: La aplicación web KiroArchery en su totalidad.
- **Organizador**: Usuario administrador con acceso al panel de gestión de torneos y arqueros.
- **Arquero**: Participante registrado en un torneo que carga sus puntuaciones mediante PIN.
- **Torneo**: Competencia de arquería con nombre, fecha, estado y categorías asociadas.
- **Categoría**: Subdivisión de un torneo definida por tipo de arco, distancia y género.
- **Registro**: Inscripción de un Arquero en una Categoría de un Torneo específico.
- **Tanda (End)**: Grupo de flechas disparadas en una misma serie dentro de una ronda.
- **Ronda**: Conjunto de tandas dentro de un torneo.
- **Flecha**: Disparo individual con un valor textual (`X`, `10`, `9`, …, `1`, `M`) y un puntaje numérico asociado.
- **PIN**: Código numérico de 4 dígitos asignado a un Arquero para autenticarse en el sistema.
- **Leaderboard**: Tabla de clasificación pública ordenada por puntaje, Xs y 10s.
- **SSE**: Server-Sent Events, mecanismo de actualización en tiempo real del servidor al cliente.
- **DB_Module**: Módulo de base de datos del Sistema encargado de la conexión a Turso o SQLite local.
- **Admin_Module**: Módulo del Sistema que gestiona torneos, categorías y arqueros.
- **Archer_Module**: Módulo del Sistema que gestiona la autenticación y carga de puntuaciones del Arquero.
- **Leaderboard_Module**: Módulo del Sistema que publica y transmite el leaderboard en tiempo real.
- **Stats_Module**: Módulo del Sistema que calcula y presenta estadísticas y reportes analíticos.

---

## Requerimientos

### Requerimiento 1: Conexión a Base de Datos

**User Story:** Como desarrollador, quiero que el sistema se conecte automáticamente a Turso o a SQLite local, para que la aplicación funcione tanto en producción como en desarrollo offline.

#### Criterios de Aceptación

1. WHEN el Sistema inicia, THE DB_Module SHALL leer las variables de entorno `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` para intentar establecer la conexión a Turso mediante el SDK `libsql-experimental` con un tiempo máximo de espera de 10 segundos.
2. IF las variables de entorno `TURSO_DATABASE_URL` o `TURSO_AUTH_TOKEN` no están definidas, THEN THE DB_Module SHALL establecer la conexión utilizando SQLite local con el archivo `db.sqlite3`.
3. IF las tablas `archers`, `tournaments`, `categories`, `registrations` o `scores` no existen en la base de datos activa, THEN THE DB_Module SHALL ejecutar los scripts de creación de dichas tablas antes de que el Sistema acepte solicitudes.
4. IF el intento de conexión a Turso no tiene éxito dentro del tiempo máximo de 10 segundos, THEN THE DB_Module SHALL registrar en el log de la aplicación el mensaje de error y su causa, y terminar el proceso con un código de error no nulo.
5. THE DB_Module SHALL exponer una función única de obtención de conexión que, al ser invocada múltiples veces, retorne siempre la misma instancia de conexión activa (Turso o SQLite local) durante el ciclo de vida de la aplicación.

---

### Requerimiento 2: Gestión de Torneos

**User Story:** Como Organizador, quiero crear y administrar torneos con sus categorías, para estructurar las competencias y separar a los participantes por tipo de arco, distancia y género.

#### Criterios de Aceptación

1. WHEN el Organizador envía un formulario de creación con un nombre de entre 1 y 150 caracteres y una fecha en formato `YYYY-MM-DD`, THE Admin_Module SHALL crear un Torneo con estado `created` y un identificador único (UUID).
2. IF el nombre del Torneo está vacío, supera los 150 caracteres o la fecha no está en formato `YYYY-MM-DD`, THEN THE Admin_Module SHALL retornar un mensaje de error que identifica el campo inválido y la razón, sin crear el registro.
3. WHEN el Organizador crea una Categoría para un Torneo existente, THE Admin_Module SHALL persistir la Categoría con los atributos `bow_type` (uno de: Recurvo, Compuesto, Raso), `distance` (ej. 70m, 50m, 18m) y `gender` (uno de: Masculino, Femenino, Mixto) asociada al `tournament_id` correspondiente.
4. IF el `tournament_id` referenciado al crear una Categoría no existe, THEN THE Admin_Module SHALL retornar un error indicando que el torneo no fue encontrado.
5. IF una combinación de `tournament_id`, `bow_type`, `distance` y `gender` idéntica ya existe en la tabla `categories`, THEN THE Admin_Module SHALL retornar un error indicando que la categoría ya existe para ese torneo, sin crear el registro duplicado.
6. WHEN el Organizador cambia el estado de un Torneo a `active`, THE Admin_Module SHALL actualizar el campo `status` del Torneo a `active` en la base de datos.
7. WHEN el Organizador cambia el estado de un Torneo a `finished`, THE Admin_Module SHALL actualizar el campo `status` del Torneo a `finished` en la base de datos.
8. IF el Organizador intenta cambiar el estado de un Torneo con estado `finished` a `created` o `active`, o el estado de un Torneo `active` a `created`, THEN THE Admin_Module SHALL retornar un error indicando que la transición de estado no está permitida.
9. WHEN el Organizador solicita el listado de Torneos, THE Admin_Module SHALL retornar todos los Torneos existentes ordenados por `created_at` descendente.

---

### Requerimiento 3: Registro de Arqueros

**User Story:** Como Organizador, quiero registrar arqueros y asignarles un PIN único, para que puedan acceder al sistema de forma rápida desde sus celulares.

#### Criterios de Aceptación

1. WHEN el Organizador crea un Arquero con un nombre de entre 1 y 100 caracteres y un PIN de exactamente 4 dígitos numéricos, THE Admin_Module SHALL persistir el Arquero con un identificador único (UUID) en la tabla `archers`.
2. IF el PIN ingresado no tiene exactamente 4 dígitos numéricos, THEN THE Admin_Module SHALL retornar un error indicando el formato requerido sin crear el registro.
3. IF el nombre del Arquero está vacío o supera los 100 caracteres, THEN THE Admin_Module SHALL retornar un error indicando el campo inválido sin crear el registro.
4. IF el PIN ingresado ya existe en la base de datos, THEN THE Admin_Module SHALL retornar un error indicando que el PIN ya está en uso, sin crear el registro.
5. WHEN el Organizador inscribe un Arquero en un Torneo con estado `created` o `active`, THE Admin_Module SHALL crear un registro en la tabla `registrations` vinculando `archer_id`, `tournament_id` y `category_id`.
6. IF el Organizador intenta inscribir un Arquero en un Torneo con estado `finished`, THEN THE Admin_Module SHALL retornar un error indicando que no se puede inscribir en un torneo finalizado.
7. IF la `category_id` proporcionada no pertenece al `tournament_id` indicado, THEN THE Admin_Module SHALL retornar un error indicando que la categoría no corresponde al torneo.
8. IF el Arquero ya está inscrito en la misma Categoría del mismo Torneo, THEN THE Admin_Module SHALL retornar un error indicando que el Arquero ya está registrado en esa categoría, sin crear el registro duplicado.
9. WHEN el Organizador solicita el listado de Arqueros, THE Admin_Module SHALL retornar todos los Arqueros registrados ordenados alfabéticamente por nombre, incluyendo nombre y PIN de cada uno.

---

### Requerimiento 4: Autenticación del Arquero por PIN

**User Story:** Como Arquero, quiero ingresar al sistema solo con mi PIN de 4 dígitos, para acceder rápidamente desde mi celular sin necesidad de usuario y contraseña complejos.

#### Criterios de Aceptación

1. WHEN el Arquero ingresa un PIN de exactamente 4 dígitos numéricos (incluyendo ceros a la izquierda) que existe en la base de datos, THE Archer_Module SHALL iniciar una sesión autenticada y redirigir al Arquero a su vista de carga de puntuaciones.
2. IF el PIN ingresado no coincide con ningún Arquero registrado, THEN THE Archer_Module SHALL mostrar un mensaje de error genérico indicando "PIN incorrecto" sin incluir ni confirmar datos de otros arqueros.
3. IF el Arquero autenticado no está inscrito en ningún Torneo con estado `active`, THEN THE Archer_Module SHALL mostrar un mensaje informando que no hay torneos activos para el arquero.
4. WHILE el Arquero tiene una sesión activa y ha interactuado con el sistema en los últimos 30 minutos, THE Archer_Module SHALL mantener la sesión sin requerir reautenticación.
5. WHEN el Arquero cierra sesión, THE Archer_Module SHALL invalidar la sesión activa y redirigir a la pantalla de ingreso de PIN.
6. IF el valor ingresado en el campo de PIN no tiene exactamente 4 dígitos numéricos, THEN THE Archer_Module SHALL rechazar el envío del formulario y mostrar el formato requerido antes de intentar consultar la base de datos.
7. IF un Arquero realiza 5 intentos consecutivos de autenticación fallidos, THEN THE Archer_Module SHALL bloquear nuevos intentos de autenticación para ese PIN durante 5 minutos y mostrar un mensaje indicando el tiempo de espera.

---

### Requerimiento 5: Carga de Puntuaciones (Teclado Táctil)

**User Story:** Como Arquero, quiero registrar mis flechas flecha por flecha usando un teclado táctil de botones grandes en mi celular, para ingresar mis puntuaciones de forma rápida y sin errores en campo.

#### Criterios de Aceptación

1. THE Archer_Module SHALL presentar un teclado táctil con los valores `X`, `10`, `9`, `8`, `7`, `6`, `5`, `4`, `3`, `2`, `1`, `M` como botones individuales de tamaño mínimo 60×60 píxeles.
2. WHEN el Arquero toca un botón de valor de flecha y el Arquero está autenticado e inscripto en un Torneo `active`, THE Archer_Module SHALL persistir en la tabla `scores` los atributos `tournament_id`, `archer_id`, `round_number`, `end_number`, `arrow_val` (valor textual: `"X"`, `"10"`, …, `"M"`) y `points` (`X`→10, `10`→10, `9`→9, …, `1`→1, `M`→0), y reflejar el valor registrado en el campo de puntuación activo de la pantalla.
3. IF la persistencia de la flecha en la base de datos falla, THEN THE Archer_Module SHALL revertir el contador de la tanda en curso, mostrar un mensaje de error al Arquero e impedir avanzar hasta que la operación se complete con éxito.
4. IF el Arquero intenta registrar una flecha y no está inscripto en ningún Torneo `active`, THEN THE Archer_Module SHALL bloquear la acción y mostrar un mensaje indicando que no hay torneos activos asignados.
5. IF el Arquero intenta registrar una flecha en un Torneo con estado distinto de `active`, THEN THE Archer_Module SHALL bloquear la acción y mostrar un mensaje indicando que el torneo no está activo.
6. WHEN el Arquero registra la última flecha de la tanda (según la cantidad de flechas por tanda configurada para su categoría), THE Archer_Module SHALL mostrar un resumen de la tanda con los valores individuales de cada flecha y el subtotal de puntos de la tanda.
7. WHILE la pantalla de carga de puntuaciones está activa, THE Archer_Module SHALL mostrar el total acumulado de puntos del Arquero en el torneo activo, actualizándolo tras cada flecha registrada.

---

### Requerimiento 6: Leaderboard en Vivo

**User Story:** Como espectador u Organizador, quiero ver la clasificación actualizada en tiempo real por categoría, para seguir el progreso del torneo sin necesidad de recargar la página.

#### Criterios de Aceptación

1. THE Leaderboard_Module SHALL exponer un endpoint público que transmita actualizaciones del leaderboard mediante Server-Sent Events (SSE) sin requerir autenticación.
2. WHEN un Arquero registra una flecha con éxito, THE Leaderboard_Module SHALL emitir un evento SSE con los datos actualizados del leaderboard en un plazo máximo de 2 segundos desde la confirmación de persistencia de la flecha.
3. THE Leaderboard_Module SHALL ordenar a los Arqueros dentro de cada Categoría por: Total de puntos (DESC), cantidad de Xs (DESC), cantidad de 10s (DESC).
4. THE Leaderboard_Module SHALL agrupar y presentar el leaderboard desglosado por Categoría, mostrando para cada Arquero: posición, nombre, total de puntos, cantidad de Xs y cantidad de 10s.
5. WHILE un cliente está conectado al stream SSE, THE Leaderboard_Module SHALL enviar un evento de tipo `heartbeat` cada 30 segundos para mantener la conexión activa.
6. WHEN un cliente se conecta al endpoint SSE (incluyendo reconexiones tras una interrupción), THE Leaderboard_Module SHALL enviar inmediatamente el estado actual completo del leaderboard como primer evento.
7. THE Leaderboard_Module SHALL soportar múltiples clientes conectados simultáneamente al stream SSE sin degradación en el plazo de emisión establecido en el criterio 2.

---

### Requerimiento 7: Estadísticas por Torneo

**User Story:** Como Arquero u Organizador, quiero ver estadísticas de rendimiento dentro de un torneo específico, para analizar el desempeño ronda por ronda.

#### Criterios de Aceptación

1. WHEN se solicita el reporte de un Torneo, THE Stats_Module SHALL calcular el promedio de puntos por flecha para cada Arquero inscrito en ese torneo, redondeado a 2 decimales.
2. WHEN se solicita el reporte de un Torneo, THE Stats_Module SHALL calcular el porcentaje de flechas en zona alta (valores `X` o `10`) sobre el total de flechas registradas por Arquero en ese torneo, redondeado a 2 decimales.
3. WHEN se solicita el reporte de un Torneo, THE Stats_Module SHALL retornar la evolución de puntos totales por ronda para cada Arquero en orden ascendente de `round_number`, como serie de datos apta para Chart.js.
4. IF un Arquero no tiene flechas registradas en un Torneo, THEN THE Stats_Module SHALL retornar valores en cero (promedio: 0.00, porcentaje: 0.00, serie vacía) para todas las métricas de ese Arquero en ese torneo.
5. WHEN el Organizador o el Arquero autenticado solicita el endpoint de estadísticas de un Torneo, THE Stats_Module SHALL retornar los datos en formato JSON; los Arqueros solo podrán acceder a sus propios datos, mientras que el Organizador puede acceder a todos.
6. IF el `tournament_id` solicitado no existe en la base de datos, THEN THE Stats_Module SHALL retornar un error HTTP 404 con un mensaje indicando que el torneo no fue encontrado.
7. WHEN un Arquero autenticado solicita el reporte de un Torneo, THE Stats_Module SHALL retornar únicamente las métricas correspondientes a ese Arquero, sin exponer datos de otros participantes.

---

### Requerimiento 8: Tendencia Histórica del Arquero

**User Story:** Como Arquero, quiero ver la evolución de mi rendimiento a lo largo de múltiples torneos, para identificar mi progreso a largo plazo.

#### Criterios de Aceptación

1. WHEN se solicita la tendencia histórica de un Arquero, THE Stats_Module SHALL retornar el promedio de puntos por flecha (redondeado a 2 decimales) del Arquero en cada Torneo con `status = 'finished'` en que participó, ordenado por fecha del Torneo de forma ascendente.
2. WHEN se solicita la tendencia histórica de un Arquero, THE Stats_Module SHALL retornar la serie de datos en formato JSON compatible con Chart.js (arreglo de objetos con nombre del torneo, fecha y promedio de puntos por flecha).
3. IF el Arquero no ha participado en ningún Torneo con `status = 'finished'`, THEN THE Stats_Module SHALL retornar un arreglo vacío `[]`.
4. IF el Arquero tiene registros en un torneo `finished` pero no tiene flechas registradas (scores) en ese torneo, THEN THE Stats_Module SHALL incluir ese torneo en la serie con promedio = 0.00.

---

### Requerimiento 9: Ranking Global Acumulado

**User Story:** Como Organizador o visitante, quiero ver un ranking general de todos los arqueros con sus estadísticas acumuladas históricas, para identificar a los mejores arqueros de la plataforma.

#### Criterios de Aceptación

1. WHEN se solicita el ranking global, THE Stats_Module SHALL calcular y retornar una tabla que incluya todos los Arqueros registrados con: nombre, total de puntos acumulados en todos los torneos `finished`, promedio histórico de puntos por flecha (total de puntos / total de flechas, redondeado a 2 decimales) y cantidad de torneos `finished` disputados.
2. WHEN se solicita el ranking global, THE Stats_Module SHALL ordenar los resultados por total de puntos acumulados de forma descendente; en caso de empate, los Arqueros con igual puntaje deberán aparecer ordenados alfabéticamente por nombre de forma ascendente.
3. THE Stats_Module SHALL incluir en el ranking global únicamente puntos provenientes de Torneos con estado `finished`.
4. IF un Arquero no ha participado en ningún Torneo con estado `finished`, THE Stats_Module SHALL incluirlo en el ranking con total de puntos = 0, promedio = 0.00 y torneos disputados = 0.
5. WHEN se solicita el ranking global, THE Stats_Module SHALL retornar los datos en formato JSON.
6. IF la base de datos no está disponible al momento de la solicitud, THEN THE Stats_Module SHALL retornar un error HTTP 503 con un mensaje indicando que el servicio no está disponible temporalmente.

---

### Requerimiento 10: Interfaz Responsiva Mobile-First

**User Story:** Como Arquero, quiero que la interfaz funcione correctamente en mi celular en campo de tiro, para poder cargar mis puntuaciones sin dificultades en condiciones reales.

#### Criterios de Aceptación

1. THE Sistema SHALL renderizar todas sus vistas utilizando Tailwind CSS via CDN con un layout mobile-first (breakpoint base para pantallas de 360px de ancho mínimo).
2. WHEN el Arquero accede a la vista de carga de puntuaciones, THE Archer_Module SHALL presentar el teclado táctil con botones de tamaño mínimo 60×60 píxeles y un espaciado mínimo de 8px entre botones adyacentes para evitar toques accidentales.
3. WHEN el Arquero toca un botón del teclado táctil en la vista de carga, THE Sistema SHALL registrar el valor en el campo de puntuación activo en menos de 300ms sin requerir recarga de página.
4. WHEN el Arquero navega a la vista de estadísticas o tendencia histórica, THE Sistema SHALL utilizar Chart.js via CDN para renderizar todos los gráficos de estadísticas y tendencias históricas.
5. WHEN Alpine.js está disponible via CDN y el Arquero interactúa con elementos dinámicos de la interfaz, THE Sistema SHALL utilizar Alpine.js para manejar la interactividad del lado del cliente (toggles, actualizaciones de UI reactivas); IF Alpine.js no carga correctamente desde el CDN, THEN THE Sistema SHALL mantener todas las funcionalidades de carga de puntuaciones operativas en modo estático sin bloquear la operación principal.
