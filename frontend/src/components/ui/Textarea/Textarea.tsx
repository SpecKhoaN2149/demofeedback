import { useId } from 'react'
import type { TextareaHTMLAttributes } from 'react'
import styles from './Textarea.module.css'

export interface TextareaProps
  extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Visible label rendered above the textarea. Required for accessibility. */
  label: string
  /** When set to a non-empty string, puts the textarea into its error state. */
  error?: string
  /** Optional helper text rendered below the textarea when there is no error. */
  helpText?: string
  /** Number of visible text rows, controlling the textarea height. */
  rows?: number
}

export default function Textarea({
  label,
  error,
  helpText,
  rows,
  id,
  className,
  ...rest
}: TextareaProps) {
  const generatedId = useId()
  const textareaId = id ?? generatedId
  const errorId = `${textareaId}-error`
  const helpId = `${textareaId}-help`

  const hasError = Boolean(error)

  // Link the textarea to its error message (preferred) or help text via
  // aria-describedby so assistive tech announces the association.
  const describedBy = hasError ? errorId : helpText ? helpId : undefined

  const textareaClassName = [
    styles.textarea,
    hasError ? styles.error : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={styles.wrapper}>
      <label htmlFor={textareaId} className={styles.label}>
        {label}
      </label>
      <textarea
        {...rest}
        id={textareaId}
        rows={rows}
        className={textareaClassName}
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
