import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import Input from '../components/ui/Input/Input'
import Button from '../components/ui/Button/Button'
import styles from './StatusLookup.module.css'

/**
 * Status lookup page (route: /status).
 *
 * Provides an entry point for the header "Track Status" link. Customers enter
 * the submission ID they received after submitting feedback and are routed to
 * the live StatusTracker at /status/:id.
 */
export default function StatusLookup() {
  const navigate = useNavigate()
  const [submissionId, setSubmissionId] = useState('')
  const [error, setError] = useState<string | undefined>(undefined)

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = submissionId.trim()
    if (trimmed.length === 0) {
      setError('Please enter your submission ID.')
      return
    }
    setError(undefined)
    navigate(`/status/${encodeURIComponent(trimmed)}`)
  }

  return (
    <NavigationShell>
      <div className={styles.page}>
        <Card>
          <h1 className={styles.title}>Track your submission</h1>
          <p className={styles.subtitle}>
            Enter the submission ID you received when you sent us your feedback.
          </p>
        </Card>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <Input
            id="submission-id"
            label="Submission ID"
            type="text"
            value={submissionId}
            onChange={(e) => setSubmissionId(e.target.value)}
            error={error}
            helpText="Looks like a series of letters and numbers, e.g. abc-123."
          />
          <Button type="submit" variant="primary" size="large" fullWidth>
            Track Status
          </Button>
        </form>
      </div>
    </NavigationShell>
  )
}
