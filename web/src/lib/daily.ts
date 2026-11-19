import type { Recipe } from './api';
import { averageStars, daysSince } from './cooked';
import { tagWord } from './tiles';

/** Seasons as they appear in the Notion tags; the months at the edges count for both. */
const SEASONS_BY_MONTH: string[][] = [
  ['winter'], ['winter'], ['winter', 'frühling'], ['frühling'], ['frühling', 'sommer'], ['sommer'],
  ['sommer'], ['sommer', 'herbst'], ['herbst'], ['herbst'], ['herbst', 'winter'], ['winter'],
];
const SEASON_NAMES: Record<string, string> = { winter: 'Winter', 'frühling': 'Frühling', sommer: 'Sommer', herbst: 'Herbst' };
const FAVOURITE = new Set(['favourite', 'favorite', 'favorit', 'favoriten']);

export type DailyPick = { recipe: Recipe; reason: string };

function words(recipe: Recipe): string[] {
  return recipe.tags.map((tag) => tagWord(tag).toLocaleLowerCase('de'));
}

/** Same order for everyone on the same day, a different one the next day. */
function shuffled(recipes: Recipe[], seed: string): Recipe[] {
  const hash = (text: string) => {
    let h = 2166136261;
    for (const char of text) h = Math.imul(h ^ char.charCodeAt(0), 16777619) >>> 0;
    return h;
  };
  return [...recipes].sort((a, b) => hash(seed + a.id) - hash(seed + b.id));
}

/**
 * Today's suggestions, best first: what is on the weekly list, then favourites that suit
 * the season, then favourites, then seasonal recipes, then the rest of the collection.
 * Nothing here calls the model; it is the same for both of you all day.
 */
/** Recently cooked recipes rest for a while, unless they are planned for the week. */
const REST_DAYS = 14;

export function dailyPicks(all: Recipe[], today: Date): DailyPick[] {
  const rested = (r: Recipe) => !r.last_cooked || daysSince(r.last_cooked, today) >= REST_DAYS;
  const fresh = all.filter((r) => r.this_week || rested(r));
  const recipes = fresh.length ? fresh : all;
  const seed = today.toISOString().slice(0, 10);
  const seasons = SEASONS_BY_MONTH[today.getMonth()];
  const season = SEASON_NAMES[seasons[0]];
  const seen = new Set<string>();
  const picks: DailyPick[] = [];
  const add = (list: Recipe[], reason: (r: Recipe) => string) => {
    for (const recipe of shuffled(list, seed)) {
      if (seen.has(recipe.id)) continue;
      seen.add(recipe.id);
      picks.push({ recipe, reason: reason(recipe) });
    }
  };
  const favourite = (r: Recipe) => words(r).some((w) => FAVOURITE.has(w));
  const seasonal = (r: Recipe) => words(r).some((w) => seasons.includes(w));
  const seasonOf = (r: Recipe) => SEASON_NAMES[words(r).find((w) => seasons.includes(w)) ?? seasons[0]] ?? season;

  add(recipes.filter((r) => r.this_week), () => 'Steht auf eurer Wochenliste');
  add(recipes.filter((r) => favourite(r) && seasonal(r)), (r) => `Euer Favorit, passt zum ${seasonOf(r)}`);
  add(recipes.filter(favourite), () => 'Einer eurer Favoriten');
  add(recipes.filter((r) => (averageStars(r) ?? 0) >= 4), () => 'Habt ihr gut bewertet');
  add(recipes.filter(seasonal), (r) => `Passt zum ${seasonOf(r)}`);
  add(recipes, () => 'Aus eurer Sammlung');
  return picks;
}
