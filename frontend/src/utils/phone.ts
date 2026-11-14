// Phone number input rules, shared by every form that takes a contact phone.
// Allowed: an optional leading "+", then digits (spaces, dashes, dots and
// parentheses are accepted as separators). 7-15 digits in total (E.164 max).

export const PHONE_MIN_DIGITS = 7;
export const PHONE_MAX_DIGITS = 15;

/** Drops every character a phone number cannot contain, as the user types. */
export function sanitizePhoneInput(value: string): string {
  const cleaned = value.replace(/[^0-9+()\-.\s]/g, "");
  // "+" is only valid as the first character.
  return cleaned.charAt(0) === "+" ? "+" + cleaned.slice(1).replace(/\+/g, "") : cleaned.replace(/\+/g, "");
}

/** Error text for an invalid phone number, or null when it is valid (blank is valid: the field is optional). */
export function phoneError(value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  if (!/^\+?[0-9()\-.\s]+$/.test(v)) return "Enter a valid phone number (digits, spaces and + - ( ) only).";
  const digits = v.replace(/\D/g, "").length;
  if (digits < PHONE_MIN_DIGITS || digits > PHONE_MAX_DIGITS) {
    return `Phone number must have ${PHONE_MIN_DIGITS}-${PHONE_MAX_DIGITS} digits.`;
  }
  return null;
}
