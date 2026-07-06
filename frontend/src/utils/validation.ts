/**
 * Pure validation functions for frontend form inputs.
 * Each returns a map of field→error message (empty map = valid).
 */

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_REGEX = /^\+?\d{7,15}$/;

export interface LandingPageData {
  name: string;
  email: string;
  phone: string;
  coreRequest: string;
}

export interface NegativeFormData {
  issueCategory: string;
  description: string;
}

export interface NeutralFormData {
  comment: string;
}

/**
 * Validates landing page form inputs.
 * Rules:
 * - name: non-empty after trim, max 100 chars
 * - contact: at least one of email or phone required
 * - email (if provided): must match local@domain.tld pattern
 * - phone (if provided): must be 7-15 digits, optionally prefixed with +
 * - coreRequest: non-empty after trim, max 2000 chars
 */
export function validateLandingPage(data: LandingPageData): Record<string, string> {
  const errors: Record<string, string> = {};

  const trimmedName = data.name.trim();
  if (trimmedName.length === 0) {
    errors.name = 'Name is required.';
  } else if (trimmedName.length > 100) {
    errors.name = 'Name must be 100 characters or fewer.';
  }

  const trimmedEmail = data.email.trim();
  const trimmedPhone = data.phone.trim();

  if (!trimmedEmail && !trimmedPhone) {
    errors.contact = 'At least one of email or phone is required.';
  }

  if (trimmedEmail && !EMAIL_REGEX.test(trimmedEmail)) {
    errors.email = 'Email must match the format local@domain.tld.';
  }

  if (trimmedPhone && !PHONE_REGEX.test(trimmedPhone)) {
    errors.phone = 'Phone must be 7–15 digits, optionally prefixed with +.';
  }

  const trimmedRequest = data.coreRequest.trim();
  if (trimmedRequest.length === 0) {
    errors.coreRequest = 'Core request is required.';
  } else if (trimmedRequest.length > 2000) {
    errors.coreRequest = 'Core request must be 2000 characters or fewer.';
  }

  return errors;
}

/**
 * Validates negative feedback form inputs.
 * Rules:
 * - issueCategory: must be non-empty (a category must be selected)
 * - description: must be at least 10 characters, max 5000
 */
export function validateNegativeForm(data: NegativeFormData): Record<string, string> {
  const errors: Record<string, string> = {};

  if (!data.issueCategory || data.issueCategory.trim().length === 0) {
    errors.issueCategory = 'Please select an issue category.';
  }

  const trimmedDesc = data.description.trim();
  if (trimmedDesc.length < 10) {
    errors.description = 'Description must be at least 10 characters.';
  } else if (trimmedDesc.length > 5000) {
    errors.description = 'Description must be 5000 characters or fewer.';
  }

  return errors;
}

/**
 * Validates neutral feedback form inputs.
 * Rules:
 * - comment: must contain at least 1 non-whitespace character, max 5000
 */
export function validateNeutralForm(data: NeutralFormData): Record<string, string> {
  const errors: Record<string, string> = {};

  const trimmedComment = data.comment.trim();
  if (trimmedComment.length === 0) {
    errors.comment = 'A comment is required.';
  } else if (trimmedComment.length > 5000) {
    errors.comment = 'Comment must be 5000 characters or fewer.';
  }

  return errors;
}
