import { useId } from 'react'
import type { SelectHTMLAttributes } from 'react'
import styles from './Select.module.css'

export interface SelectOption {
  value: string
  label: string
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  /** Visible label rendered above the select. Required for accessibility. */
  label: string
  /** When set to a non-empty string, puts the select into its error state. */
  error?: string
  /** Options rendered as <option> elements inside the <select>. */
  options: Array<SelectOption>
}

export default function Select({
  label,
  error,
  options,
  id,
  className,
  ...rest
}: SelectProps) {
  const generatedId = useId()
  const selectId = id ?? generatedId
  const errorId = `${selectId}-error`

  const hasError = Boolean(error)

  // Link the select to its error message via aria-describedby so assistive
  // tech announces the association.
  const describedBy = hasError ? errorId : undefined

  const selectClassName = [
    styles.select,
    hasError ? styles.error : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={styles.wrapper}>
      <label htmlFor={selectId} className={styles.label}>
        {label}
      </label>
      <select
        {...rest}
        id={selectId}
        className={selectClassName}
        aria-invalid={hasError || undefined}
        aria-describedby={describedBy}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hasError ? (
        <span id={errorId} className={styles.errorMessage} role="alert">
          {error}
        </span>
      ) : null}
    </div>
  )
}
