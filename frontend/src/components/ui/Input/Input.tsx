import { useId } from 'react'
import type { InputHTMLAttributes } from 'react'
import styles from './Input.module.css'

export interface InputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  /** Visible label rendered above the input. Required for accessibility. */
  label: string
  /** When set to a non-empty string, puts the input into its error state. */
  error?: string
  /** Optional helper text rendered below the input when there is no error. */
  helpText?: string
}

export default function Input({
  label,
  error,
  helpText,
  id,
  className,
  ...rest
}: InputProps) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const errorId = `${inputId}-error`
  const helpId = `${inputId}-help`

  const hasError = Boolean(error)

  // Link the input to its error message (preferred) or help text via
  // aria-describedby so assistive tech announces the association.
  const describedBy = hasError ? errorId : helpText ? helpId : undefined

  const inputClassName = [styles.input, hasError ? styles.error : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={styles.wrapper}>
      <label htmlFor={inputId} className={styles.label}>
        {label}
      </label>
      <input
        {...rest}
        id={inputId}
        className={inputClassName}
        aria-invalid={hasError || undefined}
        aria-describedby={describedBy}
      />
      {hasError ? (
        <span id={errorId} className={styles.errorMessage} role="alert">
          {error}
        </span>
      ) : helpText ? (
        <span id={helpId} className={styles.helpText}>
          {helpText}
        </span>
      ) : null}
    </div>
  )
}
