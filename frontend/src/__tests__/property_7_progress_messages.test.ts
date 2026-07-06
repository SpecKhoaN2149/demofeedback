/**
 * Property 7: Progress state maps to correct message and bar percentage
 *
 * For any submission with a given Progress_State and sentiment route, the
 * displayed progress bar percentage and status message SHALL match the expected
 * mapping. When Progress_State reaches 100%, polling SHALL stop.
 *
 * Mapping:
 * - 25 → "Awaiting Review" (neutral only)
 * - 50 → "Spectrum is working on this."
 * - 75 → "Almost there — resolution in progress."
 * - 100 + positive → "Praise received & noted!"
 * - 100 + negative/neutral → "Your issue has been resolved."
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

/** All valid progress states */
const progressStateArb = fc.constantFrom(25, 50, 75, 100);

/** All valid sentiments */
const sentimentArb = fc.constantFrom('negative', 'positive', 'neutral');

/**
 * Generates all valid (progressState, sentiment) combinations.
 * Note: 25 is only meaningful for neutral, but the function handles all combos.
 */
const validCombinationArb = fc.tuple(progressStateArb, sentimentArb);

describe('Property 7: Progress state maps to correct message and bar percentage', () => {
  it('every valid (progressState, sentiment) combination returns the correct message', () => {
    fc.assert(
      fc.property(
        validCombinationArb,
        ([progressState, sentiment]) => {
          const message = getStatusMessage(progressState, sentiment);

          switch (progressState) {
            case 25:
              expect(message).toBe('Awaiting Review');
              break;
            case 50:
              expect(message).toBe('Spectrum is working on this.');
              break;
            case 75:
              expect(message).toBe('Almost there — resolution in progress.');
              break;
            case 100:
              if (sentiment === 'positive') {
                expect(message).toBe('Praise received & noted!');
              } else {
                expect(message).toBe('Your issue has been resolved.');
              }
              break;
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('progress bar percentage always equals the progress state value', () => {
    fc.assert(
      fc.property(
        progressStateArb,
        (progressState) => {
          const percentage = getProgressBarPercentage(progressState);
          expect(percentage).toBe(progressState);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('polling stops if and only if progress state is 100%', () => {
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

  it('for progress_state === 100, isComplete concept holds (polling stops)', () => {
    fc.assert(
      fc.property(
        sentimentArb,
        (sentiment) => {
          // At 100%, regardless of sentiment, polling must stop
          expect(shouldStopPolling(100)).toBe(true);
          // And a valid message is returned (not empty)
          const message = getStatusMessage(100, sentiment);
          expect(message.length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('100% + positive returns "Praise received & noted!"', () => {
    fc.assert(
      fc.property(
        fc.constant('positive'),
        (sentiment) => {
          expect(getStatusMessage(100, sentiment)).toBe('Praise received & noted!');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('100% + negative or neutral returns "Your issue has been resolved."', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('negative', 'neutral'),
        (sentiment) => {
          expect(getStatusMessage(100, sentiment)).toBe('Your issue has been resolved.');
        }
      ),
      { numRuns: 100 }
    );
  });
});
