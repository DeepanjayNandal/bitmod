/**
 * Client-side BitMod API key handling.
 *
 * The key is entered by the user and kept in localStorage. It is deliberately
 * NOT a NEXT_PUBLIC_ environment variable: those are inlined into the
 * JavaScript bundle at build time, so the key would be readable by anyone who
 * opened devtools on the deployed site. A route that requires a key printed in
 * its own page source is not actually closed.
 *
 * The gateway accepts either `Authorization: ApiKey <key>` or an `x-api-key`
 * header and reads its allowlist from BITMOD_API_KEYS. See core/bitmod/auth.py.
 */

const STORAGE_KEY = "bitmod.apiKey"

/** The stored key, or "" when unset. Safe to call during SSR. */
export function getApiKey(): string {
  if (typeof window === "undefined") return ""
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? ""
  } catch {
    // Private browsing and some embedded webviews throw on localStorage access.
    return ""
  }
}

/** Persist the key, or clear it when given an empty string. */
export function setApiKey(key: string): void {
  if (typeof window === "undefined") return
  try {
    if (key) window.localStorage.setItem(STORAGE_KEY, key)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing useful to do; the request will simply be unauthenticated.
  }
}

/**
 * Auth headers for a gateway request.
 *
 * Returns an empty object when no key is stored, so an unauthenticated request
 * is sent and the caller can surface the 401 rather than guessing beforehand.
 * That keeps the "auth is off" deployment working with no key entered.
 */
export function authHeaders(key?: string): Record<string, string> {
  const resolved = key ?? getApiKey()
  return resolved ? { Authorization: `ApiKey ${resolved}` } : {}
}

/** Shown on a 401. Points at the field rather than reporting a raw status. */
export const MISSING_KEY_MESSAGE =
  "Add your API key. This BitMod gateway has authentication enabled, so requests need a key " +
  "from its BITMOD_API_KEYS list. Paste one into the API key field above and send again."
