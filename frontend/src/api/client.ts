/**
 * API client for communicating with the FastAPI backend.
 * All requests are proxied through Vite dev server to http://localhost:8000.
 */

const BASE_URL = '/api'

// ─── Response / Request Types ────────────────────────────────────────────────

export interface SubmissionCreatePayload {
  customer_name: string
  email?: string | null
  phone?: string | null
  core_request: string
  sentiment: 'negative' | 'positive' | 'neutral'
  // Negative-specific
  issue_category?: string | null
  detailed_description?: string | null
  // Positive-specific
  praise_text?: string | null
  social_sharing?: boolean
  // Neutral-specific
  comment_text?: string | null
}

export interface SubmissionCreateResponse {
  submission_id: string
  progress_state: number
  message: string
  warning?: string
}

export interface StatusResponse {
  submission_id: string
  progress_state: number
  sentiment: 'negative' | 'positive' | 'neutral'
  message: string
  enrichment_status: string
}

export interface StateTransition {
  previous_state: number
  new_state: number
  timestamp: string
}

export interface EnrichmentResult {
  themes: Array<{ theme: string; confidence: number }>
  sentiment_confidence: number
  severity_score: number
  severity_factors: string[]
  language_code: string | null
  language_confidence: number | null
}

export interface Submission {
  id: string
  created_at: string
  customer_name: string
  email: string | null
  phone: string | null
  core_request: string
  sentiment: 'negative' | 'positive' | 'neutral'
  progress_state: number
  issue_category: string | null
  detailed_description: string | null
  praise_text: string | null
  social_sharing: boolean
  comment_text: string | null
  enrichment_status: 'pending' | 'completed' | 'failed' | 'timeout'
  enrichment_result: EnrichmentResult | null
  state_transitions: StateTransition[]
}

export interface LoginResponse {
  token: string
  expires_at: string
  username: string
}

export interface EnrichmentSummary {
  themes: Array<{ theme: string; confidence: number }>
  severity_score: number | null
  severity_factors?: string[]
  sentiment_confidence?: number | null
  language_code?: string | null
  language_confidence?: number | null
}

export interface QueueEntry {
  submission_id: string
  created_at: string
  customer_name: string
  comment_text: string
  enrichment_status?: 'pending' | 'completed' | 'failed' | 'timeout'
  enrichment_summary: EnrichmentSummary | null
}

export interface QueueListResponse {
  items: QueueEntry[]
  limit: number
  offset: number
}

export interface SortRequest {
  target_sentiment: 'negative' | 'positive'
  issue_category?: string
}

export interface SortResponse {
  submission_id: string
  target_sentiment: 'negative' | 'positive'
  progress_state: number | null
  detail: string
}

export interface Ticket {
  id: string
  submission_id: string
  issue_category: string
  description: string
  priority: string
  status: 'open' | 'in_progress' | 'resolved'
  created_at: string
}

export interface DashboardResponse {
  total_submissions: number
  by_sentiment: Record<string, number>
  by_progress_state: Record<string, number>
  top_categories: Array<{ category: string; count: number }>
  enrichment_status_counts?: Record<string, number>
  top_themes?: Array<{ theme: string; count: number }>
  average_severity?: number | null
  by_language?: Record<string, number>
}

export interface MarketingEntry {
  submission_id: string
  customer_name: string
  praise_text: string
  social_sharing: boolean
  social_status: 'shared' | 'internal_only' | 'generation_failed'
  shareable_url: string | null
  logged_at: string
}

export interface MarketingListResponse {
  items: MarketingEntry[]
  total: number
  limit: number
  offset: number
}

export interface TimeWindow {
  start: string
  end: string
}

export interface TrendRequest {
  baseline_window: TimeWindow
  current_window: TimeWindow
}

export interface TrendReport {
  theme_spikes: Array<{ theme: string; baseline_count: number; current_count: number }>
  sentiment_shifts: Array<{ sentiment: string; baseline_ratio: number; current_ratio: number }>
  severity_escalations: Array<{ category: string; baseline_avg: number; current_avg: number }>
}

export interface LogoutResponse {
  detail: string
}

// ─── Error Handling ──────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number
  detail: string | Record<string, unknown>

  constructor(status: number, detail: string | Record<string, unknown>) {
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    super(`API error ${status}: ${message}`)
    this.status = status
    this.detail = detail
    this.name = 'ApiError'
  }
}

// ─── Core Fetch Helpers ──────────────────────────────────────────────────────

function getAuthHeaders(token?: string | null): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail: string | Record<string, unknown>
    try {
      detail = await response.json()
    } catch {
      detail = response.statusText
    }
    throw new ApiError(response.status, detail)
  }
  return response.json()
}

async function apiGet<T>(path: string, token?: string | null): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'GET',
    headers: getAuthHeaders(token),
  })
  return handleResponse<T>(response)
}

async function apiPost<T>(path: string, body: unknown, token?: string | null): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: getAuthHeaders(token),
    body: JSON.stringify(body),
  })
  return handleResponse<T>(response)
}

async function apiPatch<T>(path: string, body: unknown, token?: string | null): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'PATCH',
    headers: getAuthHeaders(token),
    body: JSON.stringify(body),
  })
  return handleResponse<T>(response)
}

// ─── Public API Methods ──────────────────────────────────────────────────────

/** POST /api/submissions — Create a new submission */
export function createSubmission(data: SubmissionCreatePayload): Promise<SubmissionCreateResponse> {
  return apiPost<SubmissionCreateResponse>('/submissions', data)
}

/** GET /api/submissions/{id}/status — Get progress state for polling */
export function getSubmissionStatus(id: string): Promise<StatusResponse> {
  return apiGet<StatusResponse>(`/submissions/${id}/status`)
}

/** GET /api/submissions/{id} — Get full submission record (admin) */
export function getSubmission(id: string, token: string): Promise<Submission> {
  return apiGet<Submission>(`/submissions/${id}`, token)
}

// ─── Auth Methods ────────────────────────────────────────────────────────────

/** POST /api/auth/login — Authenticate admin user */
export function login(username: string, password: string): Promise<LoginResponse> {
  return apiPost<LoginResponse>('/auth/login', { username, password })
}

/** POST /api/auth/logout — Invalidate session */
export function logout(token: string): Promise<LogoutResponse> {
  return apiPost<LogoutResponse>('/auth/logout', {}, token)
}

// ─── Admin Methods ───────────────────────────────────────────────────────────

/** GET /api/admin/queue — List review queue (paginated) */
export function getQueue(
  token: string,
  limit: number = 20,
  offset: number = 0
): Promise<QueueListResponse> {
  return apiGet<QueueListResponse>(`/admin/queue?limit=${limit}&offset=${offset}`, token)
}

/** PATCH /api/admin/queue/{id}/sort — Sort a neutral submission */
export function sortSubmission(
  token: string,
  id: string,
  body: SortRequest
): Promise<SortResponse> {
  return apiPatch<SortResponse>(`/admin/queue/${id}/sort`, body, token)
}

/** GET /api/admin/tickets — List open/in-progress tickets */
export function getTickets(token: string): Promise<Ticket[]> {
  return apiGet<Ticket[]>('/admin/tickets', token)
}

/** PATCH /api/admin/tickets/{id}/advance — Advance ticket status */
export function advanceTicket(token: string, id: string): Promise<Ticket> {
  return apiPatch<Ticket>(`/admin/tickets/${id}/advance`, {}, token)
}

/** GET /api/admin/dashboard — Summary stats */
export function getDashboard(token: string): Promise<DashboardResponse> {
  return apiGet<DashboardResponse>('/admin/dashboard', token)
}

/** GET /api/admin/marketing — Paginated marketing log */
export function getMarketing(
  token: string,
  limit: number = 20,
  offset: number = 0
): Promise<MarketingListResponse> {
  return apiGet<MarketingListResponse>(`/admin/marketing?limit=${limit}&offset=${offset}`, token)
}

/** POST /api/admin/trends — Run trend analysis */
export function runTrends(token: string, body: TrendRequest): Promise<TrendReport> {
  return apiPost<TrendReport>('/admin/trends', body, token)
}
