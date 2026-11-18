/** Small per-device preferences. Storage can be unavailable (private mode); then defaults apply. */
export function load<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(`kochguru.${key}`);
    return allowed.includes(value as T) ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

export function save(key: string, value: string): void {
  try {
    localStorage.setItem(`kochguru.${key}`, value);
  } catch {
    // ignore: the choice just isn't remembered
  }
}
