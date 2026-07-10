import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { createFeedback, ApiError } from '../api/client'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import Input from '../components/ui/Input/Input'
import Textarea from '../components/ui/Textarea/Textarea'
import Button from '../components/ui/Button/Button'
import Alert from '../components/ui/Alert/Alert'
import styles from './LandingPage.module.css'

/** Maximum feedback length accepted by the backend (Req 1.5). */
const MAX_FEEDBACK_LENGTH = 10000

/**
 * Pure validation helper for the single free-form feedback field (Req 1.4, 1.5).
 *
 * Returns an error string when the text is empty/whitespace-only or exceeds the
 * length limit, otherwise `undefined`. Exported for unit testing.
 */
export function validateFeedbackForm(text: string): string | undefined {
  const trimmed = text.trim()
  if (trimmed.length === 0) {
    return 'Feedback is required.'
  }
  if (text.length > MAX_FEEDBACK_LENGTH) {
    return `Feedback must be ${MAX_FEEDBACK_LENGTH} characters or fewer.`
  }
  return undefined
}

/**
 * Single free-form feedback form (Requirements 1.1, 1.2, 2.4).
 *
 * The customer types one free-form message and, optionally, a contact detail.
 * There is deliberately NO sentiment/category control anywhere on this form —
 * sentiment is derived server-side by the NLP pipeline (Req 2.4). On success we
 * send the customer to the status view for their new feedback_id so they can
 * track enrichment/triage progress.
 */
export default function FeedbackForm() {
  const navigate = useNavigate()

  const [text, setText] = useState('')
  const [contact, setContact] = useState('')
  const [fieldError, setFieldError] = useState<string | undefined>(undefined)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // On success we show the new feedback ID (so the customer can save it)
  // instead of navigating straight to the status view.
  const [submittedId, setSubmittedId] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitError(null)

    const validationError = validateFeedbackForm(text)
    if (validationError) {
      setFieldError(validationError)
      return
    }
    setFieldError(undefined)

    const trimmedContact = contact.trim()

    setSubmitting(true)
    try {
      const response = await createFeedback({
        text,
        contact: trimmedContact.length > 0 ? trimmedContact : null,
      })
      setSubmittedId(response.feedback_id)
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(
          'We could not submit your feedback. Please try again in a moment.'
        )
      } else {
        setSubmitError('Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function copyId() {
    if (!submittedId) return
    try {
      await navigator.clipboard.writeText(submittedId)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* Clipboard may be unavailable; the ID is still visible to copy manually. */
    }
  }

  function resetForm() {
    setText('')
    setContact('')
    setSubmittedId(null)
    setCopied(false)
  }

  // Success view — surface the feedback ID prominently before tracking.
  if (submittedId) {
    return (
      <NavigationShell>
        <div className={styles.page}>
          <Card>
            <h1 className={styles.title}>Thanks — we&apos;ve got your feedback</h1>
            <p className={styles.subtitle}>
              Save your feedback ID below. You can use it any time to track the
              status of your feedback.
            </p>

            <div className={styles.idLabel}>Your feedback ID</div>
            <div className={styles.idBox}>
              <code className={styles.idValue}>{submittedId}</code>
              <Button variant="outline" size="small" onClick={copyId}>
                {copied ? 'Copied!' : 'Copy'}
              </Button>
            </div>

            <div className={styles.idActions}>
              <Button
                variant="primary"
                size="large"
                onClick={() => navigate(`/status/${submittedId}`)}
              >
                Track your feedback
              </Button>
              <Button variant="ghost" size="large" onClick={resetForm}>
                Submit another response
              </Button>
            </div>
          </Card>
        </div>
      </NavigationShell>
    )
  }

  return (
    <NavigationShell>
      <div className={styles.page}>
        <Card>
          <h1 className={styles.title}>Tell us about your experience</h1>
          <p className={styles.subtitle}>
            Share your feedback in your own words. We&apos;ll analyze it and get
            it to the right place.
          </p>
        </Card>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          {submitError && (
            <Alert severity="error" onClose={() => setSubmitError(null)}>
              {submitError}
            </Alert>
          )}

          <Textarea
            id="feedback-text"
            label="Your feedback"
            rows={8}
            required
            maxLength={MAX_FEEDBACK_LENGTH}
            value={text}
            onChange={(e) => setText(e.target.value)}
            error={fieldError}
            helpText={`${text.length} / ${MAX_FEEDBACK_LENGTH} characters`}
          />

          <Input
            id="feedback-contact"
            label="Email or phone (optional)"
            type="text"
            value={contact}
            onChange={(e) => setContact(e.target.value)}
            helpText="Add a contact detail if you'd like us to follow up."
          />

          <Button
            type="submit"
            variant="primary"
            size="large"
            className={styles.submitButton}
            disabled={submitting}
          >
            {submitting ? 'Submitting…' : 'Submit feedback'}
          </Button>
        </form>
      </div>
    </NavigationShell>
  )
}
