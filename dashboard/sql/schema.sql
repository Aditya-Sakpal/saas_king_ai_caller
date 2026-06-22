-- Spice Garden — restaurant database schema
-- Target database: restaurant_db (PostgreSQL 16)

CREATE TABLE IF NOT EXISTS menu_items (
    id           SERIAL PRIMARY KEY,
    name         TEXT         NOT NULL,
    category     TEXT         NOT NULL,            -- Starters / Mains / Breads / Desserts / Drinks
    description  TEXT,
    price        NUMERIC(8,2) NOT NULL,
    is_available BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS restaurant_tables (
    id           SERIAL  PRIMARY KEY,
    table_number INTEGER NOT NULL UNIQUE,
    capacity     INTEGER NOT NULL,
    location     TEXT,                             -- Indoor / Patio / Window / Banquet
    status       TEXT    NOT NULL DEFAULT 'available'
                 CHECK (status IN ('available', 'allocated'))
);

CREATE TABLE IF NOT EXISTS bookings (
    id               SERIAL      PRIMARY KEY,
    customer_name    TEXT        NOT NULL,
    party_size       INTEGER     NOT NULL,
    booking_date     DATE        NOT NULL,
    booking_time     TIME        NOT NULL,
    table_id         INTEGER     REFERENCES restaurant_tables(id),
    special_requests TEXT,
    status           TEXT        NOT NULL DEFAULT 'confirmed'
                     CHECK (status IN ('confirmed', 'cancelled')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Q6: one row per call. The turn-by-turn transcript and per-turn latency metrics are
-- stored as JSONB arrays, so a call record and ALL its turns are written together in a
-- single atomic INSERT.
CREATE TABLE IF NOT EXISTS call_logs (
    call_id          UUID        PRIMARY KEY,
    caller_id        TEXT,                              -- anonymized SHA-256 hash; NO raw phone at rest
    start_time       TIMESTAMPTZ NOT NULL,
    end_time         TIMESTAMPTZ,
    duration_seconds INTEGER,
    booking_outcome  TEXT        NOT NULL DEFAULT 'unknown'
                     CHECK (booking_outcome IN
                        ('booked', 'failed', 'cancelled', 'menu_only', 'transferred', 'unknown')),
    transcript       JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- [{turn_id, speaker, text, started_at, ended_at, confidence}]
    metrics          JSONB       NOT NULL DEFAULT '[]'::jsonb,  -- [{type, value, at}] per-turn STT/LLM/TTS latency
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_logs_start_time ON call_logs (start_time DESC);
