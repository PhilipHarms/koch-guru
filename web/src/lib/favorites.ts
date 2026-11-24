import type { Recipe } from './api';

/** From this many stars a rating makes a recipe a favourite. */
export const FAVORITE_STARS = 4;
/** The list of what everyone likes. */
export const BOTH = 'Beide';

/**
 * How much `whose` likes a recipe: their stars, or for `BOTH` the average when everyone
 * gave at least FAVORITE_STARS. Null when it is not a favourite.
 */
export function favoriteStars(recipe: Recipe, whose: string, people: string[]): number | null {
  const ratings = recipe.ratings ?? {};
  const values = whose === BOTH ? people.map((p) => ratings[p]) : [ratings[whose]];
  if (values.length === 0 || values.some((v) => v === undefined || v < FAVORITE_STARS)) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

/** Favourites of one person or of everyone, best first. */
export function favorites(recipes: Recipe[], whose: string, people: string[]): Recipe[] {
  return recipes
    .map((recipe) => ({ recipe, stars: favoriteStars(recipe, whose, people) }))
    .filter((f): f is { recipe: Recipe; stars: number } => f.stars !== null)
    .sort((a, b) => b.stars - a.stars || a.recipe.name.localeCompare(b.recipe.name, 'de'))
    .map((f) => f.recipe);
}
