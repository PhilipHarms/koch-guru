import type { Recipe } from './api';
import { averageStars } from './cooked';
import { tagWord } from './tiles';

/**
 * The categories on Heute, in this order. A recipe belongs to one if it has one of the
 * `tags` (compared without emoji and letter case). `photo` names the recipe whose photo
 * the circle shows: its name, link or Notion id.
 */
export type CategoryDef = {
  label: string;
  tags: string[];
  photo?: string;
  /** Used only when no recipe has any of the tags, e.g. stars for "Favorit". */
  fallback?: (recipe: Recipe) => boolean;
};

const NEW_DAYS = 30;

export const CATEGORIES: CategoryDef[] = [
  {
    label: 'Neu', tags: ['neu', 'new'],
    fallback: (r) => Boolean(r.created) && Date.now() - Date.parse(r.created!) < NEW_DAYS * 86_400_000,
  },
  {
    label: 'Favorit', tags: ['favorit', 'favoriten', 'favorite', 'favourite', 'favorites', 'lieblingsrezept'],
    fallback: (r) => (averageStars(r) ?? 0) >= 4,
  },
  { label: 'Schnell', tags: ['schnell', 'quick', 'fast', 'unter 30 min'] },
  { label: 'Backen', tags: ['backen', 'baking', 'gebäck', 'kuchen', 'brot'] },
  { label: 'Veggie', tags: ['veggie', 'vegetarisch', 'vegetarian', 'vegan'] },
  { label: 'Pasta', tags: ['pasta', 'nudeln'] },
  { label: 'Italienisch', tags: ['italienisch', 'italian', 'italy', 'italien'] },
  { label: 'Asiatisch', tags: ['asiatisch', 'asian', 'asia', 'asien'] },
  { label: 'Fisch', tags: ['fisch', 'fish', 'fisch & meeresfrüchte', 'seafood'] },
  { label: 'Fleisch', tags: ['fleisch', 'meat'] },
];

const key = (tag: string) => tagWord(tag).toLocaleLowerCase('de');

/** Which recipes count for a category: by tag, or by the fallback if no recipe has the tag. */
export function categoryMatcher(def: CategoryDef, recipes: Recipe[]): ((recipe: Recipe) => boolean) | null {
  const byTag = (r: Recipe) => r.tags.some((t) => def.tags.includes(key(t)));
  if (recipes.some(byTag)) return byTag;
  if (def.fallback && recipes.some(def.fallback)) return def.fallback;
  return null;
}

const plain = (value: string) => value.trim().toLocaleLowerCase('de').replace(/-/g, '').replace(/\/+$/, '');

/** The recipe a category's `photo` names, if it is in the collection. */
export function namedRecipe(recipes: Recipe[], wanted: string | undefined): Recipe | undefined {
  if (!wanted) return undefined;
  const target = plain(wanted);
  return recipes.find((r) =>
    plain(r.name) === target || plain(r.id) === target || (r.source_url && plain(r.source_url) === target)
    || plain(r.notion_url).endsWith(target));
}
