/**
 * Shared alert-strictness vocabulary for the Parent Portal.
 *
 * The backend persists `gentle | balanced | strict`; the UI labels them
 * `lenient | normal | strict` ("Gentle / Balanced / Strict"). Both
 * SettingsTab and ParentWizard previously hand-rolled this mapping in
 * opposite directions — this module is the single source of truth.
 */

export const BACKEND_STRICTNESS = ["gentle", "balanced", "strict"] as const;
export type BackendStrictness = (typeof BACKEND_STRICTNESS)[number];

export const UI_STRICTNESS = ["lenient", "normal", "strict"] as const;
export type UiStrictness = (typeof UI_STRICTNESS)[number];

export const STRICTNESS_LABEL: Record<UiStrictness, string> = {
  lenient: "Gentle",
  normal: "Balanced",
  strict: "Strict",
};

/** UI value → persisted backend value. Unknowns fall back to balanced. */
export function toBackendStrictness(s: UiStrictness): BackendStrictness {
  return s === "lenient" ? "gentle" : s === "strict" ? "strict" : "balanced";
}

/** Persisted backend value → UI value. Unknowns fall back to normal. */
export function toUiStrictness(s?: string | null): UiStrictness {
  return s === "gentle" ? "lenient" : s === "strict" ? "strict" : "normal";
}
