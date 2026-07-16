/**
 * API client for communicating with the FastAPI backend.
 * All requests are proxied through Vite dev server to http://localhost:8000.
 */

const BASE_URL = '/api'

// ─── Response / Request Types ────────────────────────────────────────────────

/** Public feedback creation payload — free-form text + optional contact, NO sentiment (Req 1.1, 2.4). */
export interface FeedbackCreatePayload {
  text: string
  contact?: string | null
}

/** 201 response from POST /api/feedback (Req 1.8). */
export interface FeedbackCreateResponse {
  feedback_id: string
  message: string
}

/** A staff comment on a ticket as surfaced in the customer status view and admin panels (Req 7). */
export interface TicketComment {
  id: number
  ticket_id: string
  author: string
  created_at: string
  text: string
}

/** Public status view for a feedback item (Req 8, 9). */
export interface FeedbackStatus {
  feedback_id: string
  enrichment_status: 'pending' | 'completed' | 'failed' | 'timeout'
  triage_outcome: 'action_required' | 'no_action' | null
  ticket: {
    ticket_id: string
    status: 'open' | 'in_progress' | 'resolved'
  } | null
  comments: TicketComment[]
  analysis_in_progress: boolean
}

/** Admin-facing feedback row (list + detail) over the unified model (Req 10.2). */
export interface FeedbackRow {
  feedback_id: string
  text: string
  source_type: 'direct' | 'social'
  channel: string | null
  platform: 'reddit' | 'x' | 'facebook' | null
  created_at: string
  enrichment_status: string
  enrichment_result: EnrichmentResult | null
  sentiment: 'positive' | 'neutral' | 'negative' | null
  triage_outcome: 'action_required' | 'no_action' | null
  triage_decision_source: 'automated' | 'admin' | null
  needs_review: boolean
  ticket_id: string | null
  // NLP-derived routing/analytics fields.
  department: string | null
  severity: number | null // 1..10
  severity_reasoning: string | null
  location_city: string | null
  location_state: string | null
  latitude: number | null
  longitude: number | null
}

/** Admin manual triage request body (Req 3.6, 3.7). */
export interface TriagePayload {
  outcome: 'action_required' | 'no_action'
  ticket_id?: string
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
  ticket_id: string
  issue_category: string
  description: string
  priority: string
  status: 'open' | 'in_progress' | 'resolved'
  created_at: string
}

/** Ticket enriched with the number of feedback items linked to it (Req 10.4). */
export type TicketWithCount = Ticket & { linked_feedback_count: number }

/** Ticket enriched with the ids of all linked feedback records. */
export type TicketDetail = Ticket & { feedback_ids: string[] }

export interface DashboardResponse {
  total: number
  by_sentiment: Record<string, number>
  by_triage_outcome: Record<string, number>
}

/** One point on the geographic clustering map (Increment 4). */
export interface MapPoint {
  feedback_id: string
  latitude: number
  longitude: number
  city: string | null
  state: string | null
  severity: number | null
  sentiment: 'positive' | 'neutral' | 'negative' | null
  department: string | null
  source_type: 'direct' | 'social'
  platform: 'reddit' | 'x' | 'facebook' | null
  ticket_id: string | null
}

/** One row of the daily sentiment time-series. */
export interface TimeSeriesPoint {
  date: string
  total: number
  negative: number
  neutral: number
  positive: number
}

/** Per-state aggregate with average severity. */
export interface StateAgg {
  state: string
  count: number
  avg_severity: number | null
}

/** Rich analytics payload backing the dashboard charts + US map (GET /api/admin/analytics). */
export interface AnalyticsResponse {
  totals: {
    total: number
    tickets_linked: number
    needs_review: number
  }
  by_sentiment: Record<string, number>
  by_triage_outcome: Record<string, number>
  by_department: Record<string, number>
  by_source: Record<string, number>
  by_state: StateAgg[]
  severity_distribution: Record<string, number>
  average_severity: number | null
  time_series: TimeSeriesPoint[]
  map_points: MapPoint[]
}

export interface MarketingEntry {
  feedback_id: string
  text: string
  created_at: string
  source_type: 'direct' | 'social'
  platform: 'reddit' | 'x' | 'facebook' | null
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

export interface TrendWindowAgg {
  count: number
  theme_counts: Record<string, number>
  sentiment_counts: Record<string, number>
  department_counts: Record<string, number>
  average_severity: number
}

/** One day of volume across the compared windows (for the sparkline). */
export interface TrendDailyPoint {
  date: string
  baseline: number
  current: number
  total: number
}

export interface TrendReport {
  baseline?: TrendWindowAgg
  current?: TrendWindowAgg
  theme_spikes: Array<{ theme: string; baseline: number; current: number }>
  sentiment_shifts: Array<{
    sentiment: string
    baseline_ratio: number
    current_ratio: number
    delta: number
  }>
  severity_escalations: Array<{
    scope: string
    baseline_severity: number
    current_severity: number
    delta: number
  }>
  daily?: TrendDailyPoint[]
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

async function apiDelete<T>(path: string, token?: string | null): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'DELETE',
    headers: getAuthHeaders(token),
  })
  return handleResponse<T>(response)
}

// ─── Public API Methods ──────────────────────────────────────────────────────

/** POST /api/feedback — Create a new feedback item (text + optional contact, NO sentiment) */
export function createFeedback(data: FeedbackCreatePayload): Promise<FeedbackCreateResponse> {
  return apiPost<FeedbackCreateResponse>('/feedback', data)
}

/** GET /api/feedback/{id}/status — Public status view (enrichment, triage, ticket, comments) */
export function getFeedbackStatus(id: string): Promise<FeedbackStatus> {
  return apiGet<FeedbackStatus>(`/feedback/${id}/status`)
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

/** GET /api/admin/tickets — List tickets with linked feedback counts.
 *  `status` is one of "active" (default), "resolved", or "all". */
export function getTickets(
  token: string,
  status: 'active' | 'resolved' | 'all' = 'active'
): Promise<TicketWithCount[]> {
  return apiGet<TicketWithCount[]>(`/admin/tickets?status=${status}`, token)
}

/** GET /api/admin/tickets/{id} — Single ticket with linked feedback ids */
export function getTicketDetail(token: string, id: string): Promise<TicketDetail> {
  return apiGet<TicketDetail>(`/admin/tickets/${id}`, token)
}

/** GET /api/admin/review — List feedback flagged for manual triage (needs_review=1) */
export function getReviewList(
  token: string,
  limit: number = 20,
  offset: number = 0
): Promise<FeedbackRow[]> {
  return apiGet<FeedbackRow[]>(`/admin/review?limit=${limit}&offset=${offset}`, token)
}

/** GET /api/admin/review/count — Number of feedback items awaiting review */
export function getReviewCount(token: string): Promise<{ count: number }> {
  return apiGet<{ count: number }>('/admin/review/count', token)
}

/** PATCH /api/admin/feedback/{id}/triage — Submit a manual triage decision */
export function submitTriage(
  token: string,
  feedbackId: string,
  body: TriagePayload
): Promise<FeedbackRow> {
  return apiPatch<FeedbackRow>(`/admin/feedback/${feedbackId}/triage`, body, token)
}

/** GET /api/admin/feedback/{id} — Full feedback record (admin) */
export function getAdminFeedback(token: string, id: string): Promise<FeedbackRow> {
  return apiGet<FeedbackRow>(`/admin/feedback/${id}`, token)
}

/** Result of a delete operation: how many feedback/ticket rows were removed. */
export interface DeleteResult {
  deleted_feedback: number
  deleted_tickets: number
}

/** DELETE /api/admin/feedback/{id} — Delete feedback (and its ticket cluster if linked) */
export function deleteFeedback(token: string, id: string): Promise<DeleteResult> {
  return apiDelete<DeleteResult>(`/admin/feedback/${id}`, token)
}

/** DELETE /api/admin/tickets/{id} — Delete a ticket + its comments + all linked feedback */
export function deleteTicket(token: string, id: string): Promise<DeleteResult> {
  return apiDelete<DeleteResult>(`/admin/tickets/${id}`, token)
}

/** Result of a demo reset: rows removed and rows re-seeded. */
export interface DemoResetResult {
  removed: { feedback: number; tickets: number; comments: number }
  seeded: { feedback: number; tickets: number; comments: number }
}

/** POST /api/admin/demo/reset — Wipe all data and restore the fresh mock demo set */
export function resetDemo(token: string): Promise<DemoResetResult> {
  return apiPost<DemoResetResult>('/admin/demo/reset', {}, token)
}

/** GET /api/admin/feedback — List feedback rows (paginated) */
export function listAdminFeedback(
  token: string,
  limit: number = 20,
  offset: number = 0
): Promise<FeedbackRow[]> {
  return apiGet<FeedbackRow[]>(`/admin/feedback?limit=${limit}&offset=${offset}`, token)
}

/** POST /api/admin/tickets/{id}/comments — Add a staff comment to a ticket */
export function createComment(
  token: string,
  ticketId: string,
  text: string
): Promise<TicketComment> {
  return apiPost<TicketComment>(`/admin/tickets/${ticketId}/comments`, { text }, token)
}

/** GET /api/admin/tickets/{id}/comments — List a ticket's comments (ascending order) */
export function listComments(token: string, ticketId: string): Promise<TicketComment[]> {
  return apiGet<TicketComment[]>(`/admin/tickets/${ticketId}/comments`, token)
}

/** PATCH /api/admin/tickets/{id}/advance — Advance ticket status */
export function advanceTicket(token: string, id: string): Promise<Ticket> {
  return apiPatch<Ticket>(`/admin/tickets/${id}/advance`, {}, token)
}

/** GET /api/admin/dashboard — Summary stats */
export function getDashboard(token: string): Promise<DashboardResponse> {
  return apiGet<DashboardResponse>('/admin/dashboard', token)
}

/** GET /api/admin/analytics — Rich analytics for dashboard charts + US map */
export function getAnalytics(token: string): Promise<AnalyticsResponse> {
  return apiGet<AnalyticsResponse>('/admin/analytics', token)
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
