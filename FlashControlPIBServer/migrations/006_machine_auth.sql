ALTER TABLE observations ADD COLUMN IF NOT EXISTS agent_id UUID;
ALTER TABLE observations ADD COLUMN IF NOT EXISTS proxy_id UUID;
CREATE INDEX IF NOT EXISTS ix_observations_agent_id ON observations (agent_id);
CREATE INDEX IF NOT EXISTS ix_observations_proxy_id ON observations (proxy_id);
