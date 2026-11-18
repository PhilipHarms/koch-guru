import type { Recipe } from './api';
import { fold } from './text';

/**
 * Search with ranking. Every word must match somewhere; better matches come first.
 *
 * German compounds name the kind last: a Butternutkürbis is a Kürbis, Kürbiskerne are
 * Kerne. So "Kürbis" in an ingredient counts fully when it is the word itself or the
 * end of a compound, and only a little when it starts one (Kürbiskerne, Kürbiskernöl).
 */
const SCORE = { name: 100, ingredient: 80, label: 50, part: 20 } as const;

/** Short endings that still mean the same word: Tomate/Tomaten, Ei/Eier, Linse/Linsen. */
const MAX_ENDING = 2;

/** A weaker hit inside a word; short words like "Ei" only at the start (Eigelb, not Grießbrei). */
function isPart(token: string, word: string): boolean {
  return token.startsWith(word) || (word.length >= 3 && token.includes(word));
}

function words(value: string): string[] {
  return fold(value).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

/** The word itself (allowing short endings) or the last part of a compound. */
function isKind(token: string, word: string): boolean {
  const at = token.lastIndexOf(word);
  if (at < 0 || token.length - at - word.length > MAX_ENDING) return false;
  // Short words like "Ei" only count on their own, not inside "Brei".
  return at === 0 || word.length >= 4;
}

function scoreName(name: string, word: string): number {
  // In a title any mention counts: Kürbissuppe and Ofenkürbis are both about Kürbis.
  const tokens = words(name);
  if (tokens.some((t) => t.startsWith(word) || isKind(t, word))) return SCORE.name;
  return tokens.some((t) => isPart(t, word)) ? SCORE.part : 0;
}

function scoreIngredient(ingredient: string, word: string): number {
  const tokens = words(ingredient);
  if (tokens.some((t) => isKind(t, word))) return SCORE.ingredient;
  return tokens.some((t) => isPart(t, word)) ? SCORE.part : 0;
}

function scoreLabel(label: string, word: string): number {
  const tokens = words(label);
  if (tokens.some((t) => t.startsWith(word))) return SCORE.label;
  return tokens.some((t) => isPart(t, word)) ? SCORE.part : 0;
}

function scoreWord(recipe: Recipe, word: string): number {
  return Math.max(
    scoreName(recipe.name, word),
    ...recipe.ingredients.map((i) => scoreIngredient(i, word)),
    ...[...recipe.tags, ...recipe.origin].map((l) => scoreLabel(l, word)),
    0,
  );
}

export function queryWords(query: string): string[] {
  return words(query);
}

/** 0 when a word matches nowhere, otherwise higher for better matches. */
export function searchScore(recipe: Recipe, query: string[]): number {
  let total = 0;
  for (const word of query) {
    const score = scoreWord(recipe, word);
    if (!score) return 0;
    total += score;
  }
  return total;
}
