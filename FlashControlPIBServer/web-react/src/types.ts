export interface User {
  id: number | string;
  username: string;
  role: 'admin' | 'security' | 'auditor';
  enabled: boolean;
  is_local: boolean;
  active_sessions?: number;
  last_login_at_utc?: string;
  created_at_utc?: string;
}

export interface DashboardStats {
  computers: number;
  physical_devices: number;
  observations: number;
  media_states: number;
  agents_online: number;
  agents_with_backlog: number;
  identity_alerts: number;
  identity_results: Record<string, number>;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface IdentityDecision {
  result: string;
  confidence?: number;
  reasons?: string[];
}

export interface Device {
  id: string;
  vendor?: string;
  product?: string;
  vid?: string;
  pid?: string;
  storage_serial?: string;
  hardware_stable_sha256?: string;
  identity_confidence?: string;
  status?: string;
  last_seen_at?: string;
  first_seen_at?: string;
  used_on_computers?: { id: string; hostname: string }[];
  seen_user_sids?: string[];
  media_states?: MediaState[];
  recent_observations?: Observation[];
  representative_device?: unknown;
}

export interface MediaState {
  last_seen_at: string;
  media_identity_sha256: string;
  media_state_sha256: string;
}

export interface Computer {
  id: string;
  hostname: string;
  domain?: string;
  last_seen_at?: string;
  agent?: {
    id: string;
    status: string;
    agent_version?: string;
    queue_size?: number;
    selected_route?: string;
    current_ips?: string[];
    last_seen_at_utc?: string;
  };
  recent_observations?: Observation[];
  last_host?: unknown;
}

export interface Observation {
  event_id: string;
  hostname?: string;
  user_sid?: string;
  observed_at_utc?: string;
  event_type?: string;
  hardware_stable_sha256?: string;
  identity_decision?: IdentityDecision;
  physical_device_id?: string;
  raw_observation?: unknown;
}

export interface IdentityAlert {
  event_id: string;
  result: string;
  hostname?: string;
  observed_at_utc?: string;
  reasons?: string[];
  confidence?: number;
  candidate_physical_device_id?: string;
}

export interface AuditLogEntry {
  id?: number | string;
  created_at_utc: string;
  username: string;
  source_ip?: string;
  action: string;
  success: boolean;
  details?: unknown;
}
