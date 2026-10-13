import type { FormInstance } from 'antd';

import { errorCode, errorMessage, fieldErrors } from '../api/client';

type FieldData = Parameters<FormInstance['setFields']>[0];

/**
 * Put backend errors next to the right form fields: 422 `errors[]` by location, plus
 * business codes mapped to a field (e.g. { EMAIL_TAKEN: 'email' }).
 * Returns true if at least one field was marked.
 */
export function applyServerErrors(
  form: FormInstance,
  error: unknown,
  codeFields: Record<string, string> = {},
): boolean {
  const fields = fieldErrors(error);
  const code = errorCode(error);
  if (code && codeFields[code]) fields.push({ name: [codeFields[code]], errors: [errorMessage(error)] });
  if (fields.length) form.setFields(fields as FieldData);
  return fields.length > 0;
}

export const passwordRules = [
  { required: true, message: 'Enter a password' },
  { min: 8, message: 'At least 8 characters' },
  { max: 72, message: 'At most 72 characters' },
];

/** Rule for a "confirm password" field that must match `field`. */
export function matchesField(field: string, message = 'Passwords do not match') {
  return ({ getFieldValue }: { getFieldValue: (name: string) => unknown }) => ({
    validator(_: unknown, value: unknown) {
      return !value || value === getFieldValue(field) ? Promise.resolve() : Promise.reject(new Error(message));
    },
  });
}
