import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import FeedbackForm from './pages/FeedbackForm'
import StatusTracker from './pages/StatusTracker'
import StatusLookup from './pages/StatusLookup'
import TermsOfService from './pages/TermsOfService'
import PrivacyPolicy from './pages/PrivacyPolicy'
import NotFound from './pages/NotFound'
import AdminLogin from './pages/admin/AdminLogin'
import ReviewQueue from './pages/admin/ReviewQueue'
import FeedbackDetail from './pages/admin/FeedbackDetail'
import TicketList from './pages/admin/TicketList'
import TicketDetail from './pages/admin/TicketDetail'
import MarketingLog from './pages/admin/MarketingLog'
import TrendAnalysis from './pages/admin/TrendAnalysis'
import ProtectedRoute from './components/ProtectedRoute'

// The dashboard pulls in the heavy charting + mapping libraries (recharts,
// react-simple-maps, d3-geo). Lazy-load it so those only ship when an admin
// actually opens the dashboard, keeping the initial bundle small.
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'))

/**
 * App routing.
 *
 * The public entry point ("/") is now the single free-form FeedbackForm
 * (Requirements 1.1, 1.2, 2.4): the old multi-step sentiment flow
 * (LandingPage → SentimentSelect → Negative/Positive/NeutralForm) has been
 * removed in favor of NLP-derived sentiment. Every route renders inside the
 * NavigationShell layout: the customer-facing pages (FeedbackForm,
 * StatusTracker, StatusLookup) and AdminLogin each compose NavigationShell
 * themselves, while the authenticated admin pages compose AdminLayout (which
 * provides its own header/sidebar frame). Pages are wrapped at the page level
 * rather than here to avoid double-wrapping the admin layout.
 */
function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<FeedbackForm />} />
          <Route path="/status" element={<StatusLookup />} />
          <Route path="/status/:id" element={<StatusTracker />} />
          <Route path="/terms" element={<TermsOfService />} />
          <Route path="/privacy" element={<PrivacyPolicy />} />
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route
            path="/admin/dashboard"
            element={
              <ProtectedRoute>
                <Suspense fallback={<div style={{ padding: 24 }}>Loading dashboard…</div>}>
                  <AdminDashboard />
                </Suspense>
              </ProtectedRoute>
            }
          />
          <Route path="/admin/queue" element={<ProtectedRoute><ReviewQueue /></ProtectedRoute>} />
          <Route path="/admin/feedback/:id" element={<ProtectedRoute><FeedbackDetail /></ProtectedRoute>} />
          <Route path="/admin/tickets" element={<ProtectedRoute><TicketList /></ProtectedRoute>} />
          <Route path="/admin/tickets/:id" element={<ProtectedRoute><TicketDetail /></ProtectedRoute>} />
          <Route path="/admin/marketing" element={<ProtectedRoute><MarketingLog /></ProtectedRoute>} />
          <Route path="/admin/trends" element={<ProtectedRoute><TrendAnalysis /></ProtectedRoute>} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
