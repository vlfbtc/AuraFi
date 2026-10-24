/**
 * Campaign origin for the aggregate sign-up count (see services/acquisition).
 *
 * Only utm_source, utm_medium and utm_campaign are read. They stay in this tab
 * (sessionStorage, no cookie) until a sign-in succeeds, and are sent with the
 * code request and the code confirmation. The server maps them onto a closed
 * list and keeps only weekly totals, never tied to the account. Values that do
 * not even look like a convention value (an e-mail, long text) are sent as
 * "outro", so they never leave the browser or reach storage.
 */

export type AttributionField = 'utm_source' | 'utm_medium' | 'utm_campaign';
export type Attribution = Partial<Record<AttributionField, string>>;

/** Same prefix as every other key of the widget, so "clear local data" removes it. */
export const ATTRIBUTION_KEY = 'aurafi-widget-attribution-v1';
const FIELDS: readonly AttributionField[] = ['utm_source', 'utm_medium', 'utm_campaign'];
const VALUE_SHAPE = /^[a-z0-9_]{1,40}$/;
const OTHER = 'outro';

function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function sanitize(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const value = raw.trim().toLowerCase();
  if (!value) return null;
  return VALUE_SHAPE.test(value) ? value : OTHER;
}

/**
 * Reads the campaign parameters of the current address, keeps them for this
 * tab and removes the query string from the address bar. The site uses no
 * query parameter of its own, so every parameter goes, click identifiers
 * (gclid, fbclid) included; the path and the hash stay.
 */
export function captureAttribution(): void {
  if (typeof window === 'undefined') return;
  let url: URL;
  try {
    url = new URL(window.location.href);
  } catch {
    return;
  }
  if (!url.search) return;
  const found: Attribution = {};
  FIELDS.forEach((field) => {
    const value = sanitize(url.searchParams.get(field));
    if (value) found[field] = value;
  });
  if (Object.keys(found).length > 0) {
    try {
      storage()?.setItem(ATTRIBUTION_KEY, JSON.stringify(found));
    } catch {
    }
  }
  try {
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.hash}`);
  } catch {
  }
}

/** The origin kept for this tab, or null when the visit came without one. */
export function readAttribution(): Attribution | null {
  try {
    const raw = storage()?.getItem(ATTRIBUTION_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const result: Attribution = {};
    FIELDS.forEach((field) => {
      const value = sanitize((parsed as Record<string, unknown>)[field]);
      if (value) result[field] = value;
    });
    return Object.keys(result).length > 0 ? result : null;
  } catch {
    return null;
  }
}

/** Called after a successful sign-in: the origin has done its only job. */
export function clearAttribution(): void {
  try {
    storage()?.removeItem(ATTRIBUTION_KEY);
  } catch {
  }
}
