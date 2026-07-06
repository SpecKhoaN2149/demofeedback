/**
 * Property 2: Form validation rejects invalid inputs
 *
 * For any submission form input that violates validation rules (name empty after
 * trim, no contact info, email not matching pattern, phone not 7–15 digits,
 * negative description < 10 chars, neutral comment whitespace-only), the system
 * SHALL reject the submission and prevent API calls.
 *
 * **Validates: Requirements 1.2, 3.7, 5.3**
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';
import {
  validateLandingPage,
  validateNegativeForm,
  validateNeutralForm,
} from '../utils/validation';

// --- Generators ---

/** Generates strings that are empty or whitespace-only after trim */
const whitespaceOnlyArb = fc.stringOf(
  fc.constantFrom(' ', '\t', '\n', '\r', '\u00A0')
).map((s) => s || ''); // includes empty string

/** Generates invalid email strings (no @ or missing parts) */
const invalidEmailArb = fc.oneof(
  // No @ sign at all
  fc.string({ minLength: 1 }).filter((s) => !s.includes('@')),
  // Missing local part (starts with @)
  fc.string({ minLength: 1 }).map((s) => `@${s.replace(/@/g, '')}.com`),
  // Missing domain (ends with @)
  fc.string({ minLength: 1 }).map((s) => `${s.replace(/@/g, '')}@`),
  // Missing TLD (no dot after @)
  fc.string({ minLength: 1 }).map((s) => `${s.replace(/[@.]/g, '')}@nodot`),
  // Has spaces
  fc.string({ minLength: 1 }).map((s) => `user ${s}@domain.com`)
);

/** Generates phone strings that are NOT 7-15 digits (with optional + prefix) */
const invalidPhoneArb = fc.oneof(
  // Too few digits (1-6)
  fc.integer({ min: 1, max: 6 }).chain((len) =>
    fc.stringOf(fc.constantFrom('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'), {
      minLength: len,
      maxLength: len,
    })
  ),
  // Too many digits (16+)
  fc.stringOf(fc.constantFrom('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'), {
    minLength: 16,
    maxLength: 25,
  }),
  // Contains non-digit characters (not just + prefix)
  fc.string({ minLength: 2 }).filter((s) => {
    const stripped = s.startsWith('+') ? s.slice(1) : s;
    return stripped.length > 0 && !/^\d{7,15}$/.test(stripped);
  })
);

/** Generates a non-empty valid string for use in fields that need to pass */
const validNameArb = fc.string({ minLength: 1, maxLength: 50 }).filter(
  (s) => s.trim().length > 0 && s.trim().length <= 100
);

const validCoreRequestArb = fc.string({ minLength: 1, maxLength: 100 }).filter(
  (s) => s.trim().length > 0 && s.trim().length <= 2000
);

const validEmailArb = fc.tuple(
  fc.stringOf(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz0123456789'.split('')), { minLength: 1, maxLength: 10 }),
  fc.stringOf(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz'.split('')), { minLength: 1, maxLength: 10 }),
  fc.stringOf(fc.constantFrom(...'abcdefghijklmnopqrstuvwxyz'.split('')), { minLength: 2, maxLength: 5 })
).map(([local, domain, tld]) => `${local}@${domain}.${tld}`);

describe('Property 2: Form validation rejects invalid inputs', () => {
  it('rejects empty/whitespace-only name', () => {
    fc.assert(
      fc.property(
        whitespaceOnlyArb,
        validEmailArb,
        validCoreRequestArb,
        (name, email, coreRequest) => {
          const errors = validateLandingPage({ name, email, phone: '', coreRequest });
          expect(errors).toHaveProperty('name');
          expect(Object.keys(errors).length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('rejects when no email AND no phone provided', () => {
    fc.assert(
      fc.property(
        validNameArb,
        validCoreRequestArb,
        (name, coreRequest) => {
          const errors = validateLandingPage({ name, email: '', phone: '', coreRequest });
          expect(errors).toHaveProperty('contact');
          expect(Object.keys(errors).length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('rejects invalid email format', () => {
    fc.assert(
      fc.property(
        validNameArb,
        invalidEmailArb,
        validCoreRequestArb,
        (name, email, coreRequest) => {
          // Only test emails that are non-empty after trim
          fc.pre(email.trim().length > 0);
          const errors = validateLandingPage({ name, email, phone: '', coreRequest });
          // If email is non-empty and invalid, we expect either email error or contact error
          // Since phone is empty, if email is invalid, contact error should also appear
          // Actually: the validator checks email format ONLY if email is non-empty
          // And checks contact only if BOTH are empty
          // So with invalid email and no phone: we get email error (format) and contact error (no valid contact)
          // Wait - contact error fires only when both are empty strings after trim
          // If email is non-empty (even invalid), contact check passes
          // So we should just get email format error
          expect(errors).toHaveProperty('email');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('rejects invalid phone (not 7-15 digits)', () => {
    fc.assert(
      fc.property(
        validNameArb,
        invalidPhoneArb,
        validCoreRequestArb,
        (name, phone, coreRequest) => {
          fc.pre(phone.trim().length > 0);
          const errors = validateLandingPage({ name, email: '', phone, coreRequest });
          // Phone is provided but invalid → phone error
          expect(errors).toHaveProperty('phone');
        }
      ),
      { numRuns: 100 }
    );
  });

  it('rejects negative description shorter than 10 characters', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 0, maxLength: 9 }),
        (description) => {
          // Ensure it's truly < 10 chars after trim
          fc.pre(description.trim().length < 10);
          const errors = validateNegativeForm({ issueCategory: 'billing', description });
          expect(errors).toHaveProperty('description');
          expect(Object.keys(errors).length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('rejects neutral whitespace-only comment', () => {
    fc.assert(
      fc.property(
        whitespaceOnlyArb,
        (comment) => {
          const errors = validateNeutralForm({ comment });
          expect(errors).toHaveProperty('comment');
          expect(Object.keys(errors).length).toBeGreaterThan(0);
        }
      ),
      { numRuns: 100 }
    );
  });
});
