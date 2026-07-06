import { useState, FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { createSubmission, SubmissionCreatePayload } from '../api/client'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Textarea from '../components/ui/Textarea/Textarea'
import Button from '../components/ui/Button/Button'
import Alert from '../components/ui/Alert/Alert'
import pageStyles from './FormPage.module.css'

interface PageOneData {
  name: string
  email: string
  phone: string
  core_request: string
}

interface FormErrors {
  praise?: string
}

export function validatePositiveForm(praiseText: string): FormErrors {
  const errors: FormErrors = {}
  const trimmed = praiseText.trim()

  if (trimmed.length === 0) {
    errors.praise = 'Praise is required.'
  } else if (trimmed.length > 2000) {
    errors.praise = 'Praise must be 2000 characters or fewer.'
  }

  return errors
}

export default function PositiveForm() {
  const navigate = useNavigate()
  const location = useLocation()
  const pageOneData = location.state as PageOneData | undefined

  const [praiseText, setPraiseText] = useState('')
  const [socialSharing, setSocialSharing] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()

    const validationErrors = validatePositiveForm(praiseText)

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setErrors({})
    setSubmitError(null)
    setSubmitting(true)

    try {
      const payload: SubmissionCreatePayload = {
        customer_name: pageOneData?.name ?? '',
        email: pageOneData?.email || null,
        phone: pageOneData?.phone || null,
        core_request: pageOneData?.core_request ?? '',
        sentiment: 'positive',
        praise_text: praiseText.trim(),
        social_sharing: socialSharing,
      }

      const response = await createSubmission(payload)

      if (response.warning) {
        // Marketing failure warning — show warning but still navigate
        alert(response.warning)
      }

      navigate(`/status/${response.submission_id}`)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Something went wrong. Please try again.'
      setSubmitError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <NavigationShell>
      <div className={`${pageStyles.page} positive-form`}>
        <Button
          type="button"
          variant="ghost"
          size="small"
          className={pageStyles.back}
          onClick={() => navigate('/sentiment', { state: pageOneData })}
        >
          ← Back
        </Button>

        <h1 className={pageStyles.heading}>Share your positive experience</h1>

        <form onSubmit={handleSubmit} noValidate className={pageStyles.form}>
          <div>
            <Textarea
              id="praise"
              label="Your Praise"
              maxLength={2000}
              rows={5}
              value={praiseText}
              onChange={(e) => setPraiseText(e.target.value)}
              error={errors.praise}
            />
            <span className={pageStyles.charCounter}>{praiseText.length}/2000</span>
          </div>

          <label htmlFor="social-sharing" className={pageStyles.checkboxRow}>
            <input
              id="social-sharing"
              type="checkbox"
              className={pageStyles.checkbox}
              checked={socialSharing}
              onChange={(e) => setSocialSharing(e.target.checked)}
            />
            Allow social sharing of my feedback
          </label>

          {submitError && <Alert severity="error">{submitError}</Alert>}

          <Button
            type="submit"
            variant="primary"
            size="large"
            className={pageStyles.submit}
            disabled={submitting}
          >
            {submitting ? 'Submitting…' : 'Submit'}
          </Button>
        </form>
      </div>
    </NavigationShell>
  )
}
