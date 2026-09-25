import type { DateTime, ID, PageResult } from './common'

/** 会话（`08 §5`）。 */
export interface Session {
  id: ID
  user_id: ID
  username: string
  display_name: string
  login_at: DateTime
  last_active_at: DateTime
  ip: string | null
  user_agent: string | null
  device: string | null
  access_expires_at: DateTime
  refresh_expires_at: DateTime
  revoked_at: DateTime | null
  revoke_reason: 'LOGOUT' | 'ADMIN_REVOKE' | 'REVOKE_ALL' | 'TOKEN_REUSE_DETECTED' | null
  online: boolean
}

export type SessionPage = PageResult<Session>
