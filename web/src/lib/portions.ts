/**
 * Portionen umrechnen: the servings you cook for, per recipe, and amounts scaled to them.
 * The choice is kept per device, so "we always cook this for two" sticks.
 */

const FRACTIONS: Record<string, number> = { '½': 0.5, '¼': 0.25, '¾': 0.75, '⅓': 1 / 3, '⅔': 2 / 3, '⅛': 0.125 };
const NUMBER = String.raw`\d+(?:[.,]\d+)?(?:\s*[½¼¾⅓⅔⅛])?|\d+\/\d+|[½¼¾⅓⅔⅛]`;
const AMOUNT = new RegExp(String.raw`^(ca\.\s*)?(${NUMBER})(\s*[-–]\s*(${NUMBER}))?(.*)$`, 'u');
const METRIC = /^\s*(g|kg|ml|l|cl|dl)\b/i;

/** "4 Portionen", "4", "Für 4 Personen", "2–3 Portionen" (the lower one). */
export function servingsCount(servings: string | null | undefined): number | null {
  const match = /(\d+)/.exec(servings ?? '');
  const n = match ? Number(match[1]) : NaN;
  return n >= 1 && n <= 50 ? n : null;
}

function parse(value: string): number {
  const compact = value.replace(/\s+/g, '');
  if (compact.includes('/')) {
    const [a, b] = compact.split('/').map(Number);
    return b ? a / b : NaN;
  }
  const last = compact.slice(-1);
  const fraction = FRACTIONS[last] ?? 0;
  const whole = fraction ? compact.slice(0, -1) : compact;
  return (whole ? Number(whole.replace(',', '.')) : 0) + fraction;
}

/** German number for an amount: grams in steps of 5 or 10, pieces and spoons in quarters or thirds. */
function format(value: number, unit: string): string {
  const metric = METRIC.exec(unit)?.[1].toLowerCase();
  if (metric === 'g' || metric === 'ml') {
    const step = value >= 200 ? 10 : value >= 50 ? 5 : 1;
    return String(Math.max(step, Math.round(value / step) * step));
  }
  if (metric) return value.toLocaleString('de', { maximumFractionDigits: 1 }); // kg, l
  if (value >= 10) return String(Math.round(value));
  const whole = Math.floor(value);
  const rest = value - whole;
  const options: [number, string][] = [[0, ''], [0.25, '¼'], [1 / 3, '⅓'], [0.5, '½'], [2 / 3, '⅔'], [0.75, '¾'], [1, '']];
  const [near, sign] = options.reduce((best, option) => (Math.abs(option[0] - rest) < Math.abs(best[0] - rest) ? option : best));
  const units = whole + (near === 1 ? 1 : 0);
  if (units === 0 && !sign) return '¼'; // never scale down to nothing
  return `${units || ''}${sign}`;
}

/** "200 g" for 4 -> "300 g" for 6; amounts without a number at the start stay as they are. */
export function scaleAmount(amount: string | null | undefined, factor: number): string | null {
  if (!amount || factor === 1) return amount ?? null;
  const match = AMOUNT.exec(amount.trim());
  if (!match) return amount;
  const [, about = '', first, , second, rest] = match;
  const a = parse(first);
  if (!Number.isFinite(a) || a <= 0) return amount;
  let text = format(a * factor, rest);
  let top = a * factor;
  if (second) {
    const b = parse(second);
    if (Number.isFinite(b) && b > 0) {
      text += `–${format(b * factor, rest)}`;
      top = b * factor;
    }
  }
  return `${about}${text}${countUnit(rest, top)}`;
}

/** "1 Zehe" but "2 Zehen", "½ Dose" but "2 Dosen". */
const PLURALS: Record<string, string> = {
  Zehe: 'Zehen', Dose: 'Dosen', Stange: 'Stangen', Scheibe: 'Scheiben', Prise: 'Prisen',
  Packung: 'Packungen', Tasse: 'Tassen', Handvoll: 'Handvoll', Knolle: 'Knollen', Flasche: 'Flaschen',
};
const SINGULARS = Object.fromEntries(Object.entries(PLURALS).map(([one, many]) => [many, one]));

function countUnit(rest: string, value: number): string {
  const match = /^(\s*)(\p{L}+)(.*)$/u.exec(rest);
  if (!match) return rest;
  const [, space, word, after] = match;
  const swapped = value > 1 ? PLURALS[word] : SINGULARS[word];
  return swapped ? `${space}${swapped}${after}` : rest;
}

// --- Chosen servings per recipe ---------------------------------------------------------------

const KEY = 'kochguru.portionen.';

export function chosenServings(recipeId: string): number | null {
  try {
    const n = Number(localStorage.getItem(KEY + recipeId));
    return n >= 1 && n <= 50 ? n : null;
  } catch {
    return null;
  }
}

export function chooseServings(recipeId: string, servings: number | null): void {
  try {
    if (servings === null) localStorage.removeItem(KEY + recipeId);
    else localStorage.setItem(KEY + recipeId, String(servings));
  } catch {
    // not remembered, e.g. in private mode
  }
}

/** Factor for the amounts: chosen servings over the recipe's own, 1 without both. */
export function servingsFactor(recipeId: string, servings: string | null | undefined): number {
  const base = servingsCount(servings);
  const chosen = chosenServings(recipeId);
  return base && chosen ? chosen / base : 1;
}
