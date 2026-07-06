/**
 * Pure utility for mapping progress state and sentiment to status messages.
 *
 * Progress state mapping:
 * - 25  → "Awaiting Review" (neutral only)
 * - 50  → "Spectrum is working on this."
 * - 75  → "Almost there — resolution in progress."
 * - 100 → sentiment-specific completion message
 *
 * Requirements: 6.3, 6.4, 8.3, 8.4, 8.6, 8.7
 */

export type Sentiment = 'negative' | 'positive' | 'neutral';
export type ProgressState = 25 | 50 | 75 | 100;

/**
 * Returns the status message for a given progress state and sentiment.
 *
 * @param progressState - One of 25, 50, 75, or 100
 * @param sentiment - One of "negative", "positive", or "neutral"
 * @returns The user-facing status message string
 */
export function getStatusMessage(progressState: number, sentiment: string): string {
  switch (progressState) {
    case 25:
      return 'Awaiting Review';
    case 50:
      return 'Spectrum is working on this.';
    case 75:
      return 'Almost there — resolution in progress.';
    case 100:
      if (sentiment === 'positive') {
        return 'Praise received & noted!';
      }
      return 'Your issue has been resolved.';
    default:
      return '';
  }
}

/**
 * Returns the progress bar percentage for a given progress state.
 * The percentage maps directly to the progress state value.
 *
 * @param progressState - One of 25, 50, 75, or 100
 * @returns The bar percentage (same as progress state)
 */
export function getProgressBarPercentage(progressState: number): number {
  return progressState;
}

/**
 * Determines whether polling should stop for a given progress state.
 * Polling stops when progress reaches 100%.
 *
 * @param progressState - The current progress state
 * @returns true if polling should stop
 */
export function shouldStopPolling(progressState: number): boolean {
  return progressState === 100;
}
