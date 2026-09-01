CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY,
    computer_id UUID REFERENCES computers(id),
    hostname VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    agent_version VARCHAR(64) NOT NULL,
    current_ips JSONB NOT NULL,
    queue_size INTEGER NOT NULL,
    selected_route VARCHAR(32) NOT NULL,
    proxy_id UUID,
    source_ip VARCHAR(128),
    first_seen_at_utc TIMESTAMPTZ NOT NULL,
    last_seen_at_utc TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agents_computer_id ON agents (computer_id);
CREATE INDEX IF NOT EXISTS ix_agents_last_seen_at_utc ON agents (last_seen_at_utc);
