import { useState, FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { createSubmission, ApiError } from '../api/client'
import { validateNegativeForm } from '../utils/validation'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Select from '../components/ui/Select/Select'
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

const ISSUE_CATEGORIES = [
  'billing',
  'network_speed',
  'outage',
  'support_experience',
  'device_hardware',
  'pricing',
] as const

const CATEGORY_OPTIONS = [
  { value: '', label: '-- Select a category --' },
  ...ISSUE_CATEGORIES.map((category) => ({
    value: category,
    label: category.replace(/_/g, ' '),
  })),
]

const MAX_DESCRIPTION_LENGTH = 5000

export default function NegativeForm() {
  const navigate = useNavigate()
  const location = useLocation()
  const pageOneData = location.state as PageOneData | undefined

  const [issueCategory, setIssueCategory] = useState('')
  const [description, setDescription] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitError('')

    const validationErrors = validateNegativeForm({
      issueCategory,
      description,
    })

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
        sentiment: 'negative',
        issue_category: issueCategory,
        detailed_description: description.trim(),
      })

      navigate(`/status/${response.submission_id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setSubmitError(
          typeof err.detail === 'string'
            ? err.detail
            : 'Submission could not be completed. Please try again.'
        )
      } else {
        setSubmitError('Could not reach server. Please retry.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <NavigationShell>
      <div className={`${pageStyles.page} negative-form`}>
        <Button
          type="button"
          variant="ghost"
          size="small"
          className={pageStyles.back}
          onClick={() => navigate('/sentiment', { state: pageOneData })}
        >
          ← Back
        </Button>

        <h1 className={pageStyles.heading}>Tell us about your issue</h1>

        <form onSubmit={handleSubmit} noValidate className={pageStyles.form}>
          {submitError && <Alert severity="error">{submitError}</Alert>}

          <Select
            id="issue-category"
            label="Issue Category"
            value={issueCategory}
            onChange={(e) => setIssueCategory(e.target.value)}
            error={errors.issueCategory}
            options={CATEGORY_OPTIONS}
          />

          <div>
            <Textarea
              id="description"
              label="Detailed Description"
              maxLength={MAX_DESCRIPTION_LENGTH}
              rows={6}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              error={errors.description}
            />
            <span className={pageStyles.charCounter} aria-live="polite">
              {description.length}/{MAX_DESCRIPTION_LENGTH}
            </span>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="large"
            className={pageStyles.submit}
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Submitting...' : 'Submit'}
          </Button>
        </form>
      </div>
    </NavigationShell>
  )
}
