# Esquema Relacional de Base de Datos (Turso / SQLite)

```sql
CREATE TABLE IF NOT EXISTS archers (
    id TEXT PRIMARY KEY,
    pin TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tournaments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    status TEXT CHECK(status IN ('created', 'active', 'finished')) DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    tournament_id TEXT NOT NULL,
    bow_type TEXT NOT NULL, -- Recurvo, Compuesto, Raso, etc.
    distance TEXT NOT NULL, -- 70m, 50m, 18m, etc.
    gender TEXT NOT NULL,   -- Masculino, Femenino, Mixto
    FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
);

CREATE TABLE IF NOT EXISTS registrations (
    id TEXT PRIMARY KEY,
    tournament_id TEXT NOT NULL,
    archer_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
    FOREIGN KEY (archer_id) REFERENCES archers(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS scores (
    id TEXT PRIMARY KEY,
    tournament_id TEXT NOT NULL,
    archer_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    end_number INTEGER NOT NULL,
    arrow_val TEXT NOT NULL, -- "X", "10", "9", ..., "1", "M"
    points INTEGER NOT NULL,  -- X=10, 10=10, 9=9, ..., M=0
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
    FOREIGN KEY (archer_id) REFERENCES archers(id)
);