import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import LandingPage from './pages/LandingPage'
import PositiveForm from './pages/PositiveForm'
import NeutralForm from './pages/NeutralForm'
import NegativeForm from './pages/NegativeForm'
import SentimentSelect from './pages/SentimentSelect'
import StatusTracker from './pages/StatusTracker'
import StatusLookup from './pages/StatusLookup'
import TermsOfService from './pages/TermsOfService'
import PrivacyPolicy from './pages/PrivacyPolicy'
import NotFound from './pages/NotFound'
import AdminLogin from './pages/admin/AdminLogin'
import AdminDashboard from './pages/admin/AdminDashboard'
import ReviewQueue from './pages/admin/ReviewQueue'
import SubmissionDetail from './pages/admin/SubmissionDetail'
import TicketList from './pages/admin/TicketList'
import MarketingLog from './pages/admin/MarketingLog'
import TrendAnalysis from './pages/admin/TrendAnalysis'
import ProtectedRoute from './components/ProtectedRoute'

/**
 * App routing.
 *
 * Every route renders inside the NavigationShell layout (Requirement 2.1): the
 * customer-facing pages (LandingPage, SentimentSelect, StatusTracker, the
 * sentiment form pages) and AdminLogin each compose NavigationShell themselves,
 * while the authenticated admin pages compose AdminLayout (which provides its
 * own header/sidebar frame). Pages are wrapped at the page level rather than
 * here to avoid double-wrapping the admin layout. Page entry uses the shared
 * fade-in animation at the normal transition duration (Requirement 15.3), and a
 * global overflow-x guard prevents horizontal scrolling at any viewport width
 * (Requirement 14.5).
 */
function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/sentiment" element={<SentimentSelect />} />
          <Route path="/negative" element={<NegativeForm />} />
          <Route path="/positive" element={<PositiveForm />} />
          <Route path="/neutral" element={<NeutralForm />} />
          <Route path="/status" element={<StatusLookup />} />
          <Route path="/status/:id" element={<StatusTracker />} />
          <Route path="/terms" element={<TermsOfService />} />
          <Route path="/privacy" element={<PrivacyPolicy />} />
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin/dashboard" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
          <Route path="/admin/queue" element={<ProtectedRoute><ReviewQueue /></ProtectedRoute>} />
          <Route path="/admin/submissions/:id" element={<ProtectedRoute><SubmissionDetail /></ProtectedRoute>} />
          <Route path="/admin/tickets" element={<ProtectedRoute><TicketList /></ProtectedRoute>} />
          <Route path="/admin/marketing" element={<ProtectedRoute><MarketingLog /></ProtectedRoute>} />
          <Route path="/admin/trends" element={<ProtectedRoute><TrendAnalysis /></ProtectedRoute>} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
