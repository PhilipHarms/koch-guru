/** A cooking time in a step, e.g. "25 Minuten" or "1½ hours", for a timer in the cooking mode. */
export type Duration = { start: number; end: number; seconds: number };

const NUMBER = String.raw`(\d+(?:[.,]\d+)?\s*[½¼¾]?|[½¼¾])`;
const UNIT = String.raw`(Minuten|Minute|Min\.?|minutes?|mins?\.?|Stunden|Stunde|Std\.?|hours?|hrs?\.?|Sekunden|Sekunde|Sek\.?|seconds?|secs?\.?)`;
const RANGE = String.raw`(?:\s*(?:-|–|bis|to|or|oder)\s*${NUMBER})?`;
const TIME = new RegExp(`${NUMBER}${RANGE}\\s*${UNIT}(?![\\p{L}])`, 'iu');
const MORE_MINUTES = new RegExp(String.raw`^\s*(?:und|and)?\s*(\d+)\s*(?:Minuten|Min\.?|minutes?|mins?\.?)(?![\p{L}])`, 'iu');
const WORDS: [RegExp, number][] = [
  [/\b(?:eine?r?\s+)?halben?\s+Stunde\b/iu, 1800],
  [/\bhalf an hour\b/iu, 1800],
  [/\beine?r?\s+Viertelstunde\b/iu, 900],
  [/\beine?r?\s+Stunde\b/iu, 3600],
  [/\ban hour\b/iu, 3600],
];

const FRACTIONS: Record<string, number> = { '½': 0.5, '¼': 0.25, '¾': 0.75 };

function number(value: string): number {
  const compact = value.replace(/\s+/g, '');
  const fraction = FRACTIONS[compact.slice(-1)] ?? 0;
  const whole = fraction ? compact.slice(0, -1) : compact;
  return (whole ? Number(whole.replace(',', '.')) : 0) + fraction;
}

function unitSeconds(unit: string): number {
  const u = unit.toLowerCase();
  if (u.startsWith('st') || u.startsWith('h')) return 3600;
  if (u.startsWith('sek') || u.startsWith('sec')) return 1;
  return 60;
}

/** The first cooking time in a step. A range ("25–30 Minuten") starts the timer at the lower end. */
export function findDuration(text: string): Duration | null {
  let found: Duration | null = null;
  const match = TIME.exec(text);
  if (match) {
    let seconds = number(match[1]) * unitSeconds(match[3]);
    let end = match.index + match[0].length;
    if (unitSeconds(match[3]) === 3600) {
      const more = MORE_MINUTES.exec(text.slice(end)); // "1 Stunde 30 Minuten"
      if (more) {
        seconds += Number(more[1]) * 60;
        end += more[0].length;
      }
    }
    if (seconds > 0) found = { start: match.index, end, seconds: Math.round(seconds) };
  }
  for (const [pattern, seconds] of WORDS) {
    const word = pattern.exec(text);
    if (word && (!found || word.index < found.start)) found = { start: word.index, end: word.index + word[0].length, seconds };
  }
  return found;
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}
