import { useNavigate } from 'react-router-dom'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import Button from '../components/ui/Button/Button'
import styles from './NotFound.module.css'

/**
 * 404 catch-all page (route: *).
 *
 * Rendered for any unmatched URL so customers never land on a blank screen.
 * Offers clear paths back into the app (home and status lookup).
 */
export default function NotFound() {
  const navigate = useNavigate()

  return (
    <NavigationShell>
      <div className={styles.page}>
        <Card className={styles.card}>
          <p className={styles.code}>404</p>
          <h1 className={styles.title}>Page not found</h1>
          <p className={styles.message}>
            The page you're looking for doesn't exist or may have moved.
          </p>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => navigate('/')}>
              Back to home
            </Button>
            <Button variant="outline" onClick={() => navigate('/status')}>
              Track a submission
            </Button>
          </div>
        </Card>
      </div>
    </NavigationShell>
  )
}
