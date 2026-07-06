import { useState, FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { validateNeutralForm } from '../utils/validation'
import { createSubmission, ApiError } from '../api/client'
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

const MAX_COMMENT_LENGTH = 5000

export default function NeutralForm() {
  const navigate = useNavigate()
  const location = useLocation()
  const pageOneData = location.state as PageOneData | undefined

  const [comment, setComment] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitError(null)

    const validationErrors = validateNeutralForm({ comment })

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setErrors({})
    setIsSubmitting(true)

    try {
      const response = await createSubmission({
        customer_name: pageOneData?.name ?? '',
        email: pageOneData?.email || null,
        phone: pageOneData?.phone || null,
        core_request: pageOneData?.core_request ?? '',
        sentiment: 'neutral',
        comment_text: comment.trim(),
      })

      navigate(`/status/${response.submission_id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(
          err.status === 422
            ? 'Validation error: please check your input and try again.'
            : 'Submission could not be completed. Please retry.'
        )
      } else {
        setSubmitError('Submission could not be completed. Please retry.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <NavigationShell>
      <div className={`${pageStyles.page} neutral-form`}>
        <Button
          type="button"
          variant="ghost"
          size="small"
          className={pageStyles.back}
          onClick={() => navigate('/sentiment', { state: pageOneData })}
        >
          ← Back
        </Button>

        <h1 className={pageStyles.heading}>General Comment</h1>

        <form onSubmit={handleSubmit} noValidate className={pageStyles.form}>
          {submitError && <Alert severity="error">{submitError}</Alert>}

          <div>
            <Textarea
              id="comment"
              label="Your Comment"
              maxLength={MAX_COMMENT_LENGTH}
              rows={6}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              error={errors.comment}
            />
            <span className={pageStyles.charCounter} aria-live="polite">
              {comment.length}/{MAX_COMMENT_LENGTH}
            </span>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="large"
            className={pageStyles.submit}
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Submitting…' : 'Submit'}
          </Button>
        </form>
      </div>
    </NavigationShell>
  )
}
