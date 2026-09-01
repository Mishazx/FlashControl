CREATE TABLE IF NOT EXISTS computers (
    id UUID PRIMARY KEY,
    computer_key VARCHAR(64) NOT NULL UNIQUE,
    hostname VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    last_host JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS physical_devices (
    id UUID PRIMARY KEY,
    hardware_stable_sha256 VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    identity_confidence VARCHAR(32) NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    representative_device JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_physical_devices_hardware_stable_sha256
    ON physical_devices (hardware_stable_sha256);

CREATE TABLE IF NOT EXISTS media_states (
    id UUID PRIMARY KEY,
    physical_device_id UUID NOT NULL REFERENCES physical_devices(id),
    media_identity_sha256 VARCHAR(64),
    media_state_sha256 VARCHAR(64),
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    representative_media JSONB NOT NULL,
    CONSTRAINT uq_media_state_device_hashes UNIQUE
        (physical_device_id, media_identity_sha256, media_state_sha256)
);

CREATE INDEX IF NOT EXISTS ix_media_states_physical_device_id
    ON media_states (physical_device_id);

ALTER TABLE observations ADD COLUMN IF NOT EXISTS computer_id UUID REFERENCES computers(id);
ALTER TABLE observations ADD COLUMN IF NOT EXISTS physical_device_id UUID REFERENCES physical_devices(id);
ALTER TABLE observations ADD COLUMN IF NOT EXISTS media_state_id UUID REFERENCES media_states(id);

CREATE INDEX IF NOT EXISTS ix_observations_computer_id ON observations (computer_id);
CREATE INDEX IF NOT EXISTS ix_observations_physical_device_id ON observations (physical_device_id);

CREATE TABLE IF NOT EXISTS identity_decisions (
    id UUID PRIMARY KEY,
    observation_id BIGINT NOT NULL UNIQUE REFERENCES observations(id),
    result VARCHAR(32) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    auto_linked BOOLEAN NOT NULL,
    candidate_physical_device_id UUID REFERENCES physical_devices(id),
    assigned_physical_device_id UUID NOT NULL REFERENCES physical_devices(id),
    reasons JSONB NOT NULL,
    decided_at_utc TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
