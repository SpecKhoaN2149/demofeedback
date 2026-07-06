import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import Input from '../components/ui/Input/Input'
import Textarea from '../components/ui/Textarea/Textarea'
import Button from '../components/ui/Button/Button'
import styles from './LandingPage.module.css'

interface FormData {
  name: string
  email: string
  phone: string
  core_request: string
}

interface FormErrors {
  name?: string
  email?: string
  phone?: string
  contact?: string
  core_request?: string
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PHONE_REGEX = /^\+?\d{7,15}$/

export function validateLandingForm(data: FormData): FormErrors {
  const errors: FormErrors = {}

  const trimmedName = data.name.trim()
  if (trimmedName.length === 0) {
    errors.name = 'Name is required.'
  } else if (trimmedName.length > 100) {
    errors.name = 'Name must be 100 characters or fewer.'
  }

  const trimmedEmail = data.email.trim()
  const trimmedPhone = data.phone.trim()

  if (!trimmedEmail && !trimmedPhone) {
    errors.contact = 'At least one of email or phone is required.'
  }

  if (trimmedEmail && !EMAIL_REGEX.test(trimmedEmail)) {
    errors.email = 'Email must match the format local@domain.tld.'
  }

  if (trimmedPhone && !PHONE_REGEX.test(trimmedPhone)) {
    errors.phone = 'Phone must be 7–15 digits, optionally prefixed with +.'
  }

  const trimmedRequest = data.core_request.trim()
  if (trimmedRequest.length === 0) {
    errors.core_request = 'Core request is required.'
  } else if (trimmedRequest.length > 2000) {
    errors.core_request = 'Core request must be 2000 characters or fewer.'
  }

  return errors
}

export default function LandingPage() {
  const navigate = useNavigate()

  const [formData, setFormData] = useState<FormData>({
    name: '',
    email: '',
    phone: '',
    core_request: '',
  })

  const [errors, setErrors] = useState<FormErrors>({})

  function handleChange(field: keyof FormData, value: string) {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()

    const validationErrors = validateLandingForm(formData)

    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    setErrors({})

    navigate('/sentiment', {
      state: {
        name: formData.name.trim(),
        email: formData.email.trim(),
        phone: formData.phone.trim(),
        core_request: formData.core_request.trim(),
      },
    })
  }

  return (
    <NavigationShell>
      <div className={styles.page}>
        <Card>
          <h1 className={styles.title}>Tell us about your experience</h1>
          <p className={styles.subtitle}>
            A few quick details help us get back to you faster.
          </p>
        </Card>

        <form className={styles.form} onSubmit={handleSubmit} noValidate>
          <Input
            id="name"
            label="Name"
            type="text"
            maxLength={100}
            value={formData.name}
            onChange={(e) => handleChange('name', e.target.value)}
            error={errors.name}
          />

          <Input
            id="email"
            label="Email"
            type="text"
            value={formData.email}
            onChange={(e) => handleChange('email', e.target.value)}
            error={errors.email}
          />

          <Input
            id="phone"
            label="Phone"
            type="text"
            value={formData.phone}
            onChange={(e) => handleChange('phone', e.target.value)}
            error={errors.phone}
          />

          {errors.contact && (
            <span id="contact-error" className={styles.contactError} role="alert">
              {errors.contact}
            </span>
          )}

          <Textarea
            id="core_request"
            label="Core Request"
            maxLength={2000}
            rows={5}
            value={formData.core_request}
            onChange={(e) => handleChange('core_request', e.target.value)}
            error={errors.core_request}
          />

          <Button
            type="submit"
            variant="primary"
            size="large"
            className={styles.submitButton}
          >
            Continue
          </Button>
        </form>
      </div>
    </NavigationShell>
  )
}
