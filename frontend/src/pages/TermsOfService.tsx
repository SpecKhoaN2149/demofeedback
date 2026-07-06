import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import styles from './LegalPage.module.css'

/**
 * Terms of Service page (route: /terms).
 *
 * Static informational content linked from the footer. Placeholder copy that
 * establishes the page so the footer link is never a dead end.
 */
export default function TermsOfService() {
  return (
    <NavigationShell>
      <div className={styles.page}>
        <Card>
          <h1 className={styles.title}>Terms of Service</h1>
          <p className={styles.updated}>Last updated: January 2026</p>

          <h2 className={styles.heading}>Acceptance of terms</h2>
          <p className={styles.body}>
            By using the Spectrum feedback portal you agree to these terms.
            This service lets you share feedback about your experience and track
            the progress of your submission.
          </p>

          <h2 className={styles.heading}>Use of the service</h2>
          <p className={styles.body}>
            You agree to provide accurate information and to use the portal only
            for legitimate feedback. We may use the details you submit to
            respond to your request and improve our services.
          </p>

          <h2 className={styles.heading}>Contact</h2>
          <p className={styles.body}>
            Questions about these terms can be directed to your Spectrum support
            representative.
          </p>
        </Card>
      </div>
    </NavigationShell>
  )
}
