import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import styles from './LegalPage.module.css'

/**
 * Privacy Policy page (route: /privacy).
 *
 * Static informational content linked from the footer. Placeholder copy that
 * establishes the page so the footer link is never a dead end.
 */
export default function PrivacyPolicy() {
  return (
    <NavigationShell>
      <div className={styles.page}>
        <Card>
          <h1 className={styles.title}>Privacy Policy</h1>
          <p className={styles.updated}>Last updated: January 2026</p>

          <h2 className={styles.heading}>Information we collect</h2>
          <p className={styles.body}>
            When you submit feedback we collect the contact details and comments
            you provide. This information is used to respond to your request and
            to understand trends in customer experience.
          </p>

          <h2 className={styles.heading}>How we use your information</h2>
          <p className={styles.body}>
            Your feedback is routed to the appropriate team based on its content.
            Positive feedback may be shared publicly only when you explicitly opt
            in to social sharing.
          </p>

          <h2 className={styles.heading}>Your choices</h2>
          <p className={styles.body}>
            You can request access to or deletion of the information tied to your
            submission by contacting your Spectrum support representative.
          </p>
        </Card>
      </div>
    </NavigationShell>
  )
}
