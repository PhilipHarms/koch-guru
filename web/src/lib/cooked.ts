import type { Recipe } from './api';

/** Whole days between a YYYY-MM-DD date and today, in local time. */
export function daysSince(day: string, today = new Date()): number {
  const [y, m, d] = day.split('-').map(Number);
  const then = new Date(y, m - 1, d);
  const now = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((now.getTime() - then.getTime()) / 86_400_000);
}

/** "heute gekocht", "vor 12 Tagen gekocht", "vor 3 Monaten gekocht". */
export function cookedLabel(day: string, today = new Date()): string {
  const days = daysSince(day, today);
  if (days <= 0) return 'Heute gekocht';
  if (days === 1) return 'Gestern gekocht';
  if (days < 28) return `Vor ${days} Tagen gekocht`;
  const months = Math.round(days / 30);
  if (months < 12) return months <= 1 ? 'Vor einem Monat gekocht' : `Vor ${months} Monaten gekocht`;
  const years = Math.round(days / 365);
  return years <= 1 ? 'Vor einem Jahr gekocht' : `Vor ${years} Jahren gekocht`;
}

/** Average stars, or null without ratings. */
export function averageStars(recipe: Recipe): number | null {
  const values = Object.values(recipe.ratings ?? {});
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

export function starsText(value: number): string {
  return `★ ${value.toLocaleString('de', { maximumFractionDigits: 1 })}`;
}

/** Today as YYYY-MM-DD in local time, like the server's "Zuletzt gekocht". */
export function localToday(today = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
}
