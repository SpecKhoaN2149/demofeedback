/**
 * Property 7: Progress state maps to correct message and bar percentage
 *
 * For any submission with a given Progress_State and sentiment route, the
 * displayed progress bar percentage and status message SHALL be:
 * 25%→"Awaiting Review" (neutral only), 50%→"Spectrum is working on this.",
 * 75%→"Almost there — resolution in progress.", 100%→completion message
 * (sentiment-specific). Furthermore, when Progress_State reaches 100%,
 * polling SHALL stop.
 *
 * **Validates: Requirements 6.3, 6.4, 8.3, 8.4, 8.6, 8.7, 12.3**
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  getStatusMessage,
  getProgressBarPercentage,
  shouldStopPolling,
} from '../utils/statusMessages';

// --- Generators ---

/** Generates valid progress states */
const progressStateArb = fc.constantFrom(25, 50, 75, 100);

/** Generates valid sentiment strings */
const sentimentArb = fc.constantFrom('negative', 'positive', 'neutral');

/** Expected messages for each progress state */
const expectedMessages: Record<number, string | Record<string, string>> = {
  25: 'Awaiting Review',
  50: 'Spectrum is working on this.',
  75: 'Almost there — resolution in progress.',
  100: {
    positive: 'Praise received & noted!',
    negative: 'Your issue has been resolved.',
    neutral: 'Your issue has been resolved.',
  },
};

describe('Property 7: Progress state maps to correct message and bar percentage', () => {
  it('maps progress state and sentiment to the correct status message', () => {
    fc.assert(
      fc.property(
        progressStateArb,
        sentimentArb,
        (progressState, sentiment) => {
          const message = getStatusMessage(progressState, sentiment);

          if (progressState === 100) {
            const expected = (expectedMessages[100] as Record<string, string>)[sentiment];
            expect(message).toBe(expected);
          } else {
            expect(message).toBe(expectedMessages[progressState] as string);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('progress bar percentage equals the progress state value', () => {
    fc.assert(
      fc.property(
        progressStateArb,
        sentimentArb,
        (progressState, _sentiment) => {
          const percentage = getProgressBarPercentage(progressState);
          expect(percentage).toBe(progressState);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('polling stops when and only when progress state reaches 100%', () => {
    fc.assert(
      fc.property(
        progressStateArb,
        (progressState) => {
          const shouldStop = shouldStopPolling(progressState);
          if (progressState === 100) {
            expect(shouldStop).toBe(true);
          } else {
            expect(shouldStop).toBe(false);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('100% with positive sentiment returns praise message', () => {
    fc.assert(
      fc.property(
        fc.constant('positive'),
        (sentiment) => {
          const message = getStatusMessage(100, sentiment);
          expect(message).toBe('Praise received & noted!');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('100% with negative or neutral sentiment returns resolution message', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('negative', 'neutral'),
        (sentiment) => {
          const message = getStatusMessage(100, sentiment);
          expect(message).toBe('Your issue has been resolved.');
        }
      ),
      { numRuns: 100 }
    );
  });
});
