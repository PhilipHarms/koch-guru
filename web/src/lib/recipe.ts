import type { Recipe } from './api';

/** Where a recipe comes from: the Origin field in Notion, else it is our own. */
export function sourceOf(recipe: Recipe): string {
  return recipe.origin[0] || 'Eigenes Rezept';
}

/** Address of the recipe page; page ids without dashes keep links short. */
export function recipePath(recipe: Recipe): string {
  return `/rezepte/${recipe.id.replace(/-/g, '')}`;
}

export function sameId(a: string, b: string): boolean {
  return a.replace(/-/g, '') === b.replace(/-/g, '');
}

/** The external recipe link, if there is a usable one. */
export function sourceLink(recipe: Recipe): string | null {
  const url = recipe.source_url;
  return url && /^https?:\/\//.test(url) ? url : null;
}

export function messageOf(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Das hat nicht geklappt. Bitte versuch es gleich noch einmal.';
}
