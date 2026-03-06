CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    channel TEXT NOT NULL,
    plate TEXT NOT NULL,
    country TEXT,
    confidence DOUBLE PRECISION,
    source TEXT,
    frame_path TEXT,
    plate_path TEXT,
    direction TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel);
CREATE INDEX IF NOT EXISTS idx_events_plate ON events(plate);
