import { useLocation, useNavigate } from 'react-router-dom'
import NavigationShell from '../components/layout/NavigationShell/NavigationShell'
import Card from '../components/ui/Card/Card'
import Button from '../components/ui/Button/Button'
import styles from './SentimentSelect.module.css'

interface PageOneData {
  name: string
  email: string
  phone: string
  core_request: string
}

interface SentimentOption {
  id: 'negative' | 'positive' | 'neutral'
  icon: string
  title: string
  description: string
  route: string
  accentClass: string
}

const sentiments: SentimentOption[] = [
  {
    id: 'negative',
    icon: '😞',
    title: 'I have a complaint',
    description: 'Report an issue for resolution',
    route: '/negative',
    accentClass: styles.negative,
  },
  {
    id: 'positive',
    icon: '😊',
    title: 'I have praise',
    description: 'Share a compliment or kind word',
    route: '/positive',
    accentClass: styles.positive,
  },
  {
    id: 'neutral',
    icon: '😐',
    title: 'I have a general comment',
    description: 'Leave feedback or a suggestion',
    route: '/neutral',
    accentClass: styles.neutral,
  },
]

export default function SentimentSelect() {
  const navigate = useNavigate()
  const location = useLocation()
  const pageOneData = location.state as PageOneData | undefined

  function handleSelect(route: string) {
    navigate(route, { state: pageOneData })
  }

  return (
    <NavigationShell>
      <div className="sentiment-select">
        <Button
          type="button"
          variant="ghost"
          size="small"
          className={styles.back}
          onClick={() => navigate('/', { state: pageOneData })}
        >
          ← Back
        </Button>
        <h1 className={styles.heading}>How would you describe your experience?</h1>
        <div className={styles.cards} role="group" aria-label="Sentiment selection">
          {sentiments.map((sentiment) => (
            <Card
              key={sentiment.id}
              interactive
              className={`${styles.card} ${sentiment.accentClass}`}
              onClick={() => handleSelect(sentiment.route)}
              aria-label={`${sentiment.title}: ${sentiment.description}`}
            >
              <span className={styles.icon} aria-hidden="true">
                {sentiment.icon}
              </span>
              <span className={styles.title}>{sentiment.title}</span>
              <span className={styles.description}>{sentiment.description}</span>
            </Card>
          ))}
        </div>
      </div>
    </NavigationShell>
  )
}
