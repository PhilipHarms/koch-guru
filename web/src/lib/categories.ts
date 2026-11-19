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
  /** Show a different one of its recipes with a photo each day. */
  rotate?: boolean;
  /** Used only when no recipe has any of the tags, e.g. stars for "Favorit". */
  fallback?: (recipe: Recipe) => boolean;
};

const NEW_DAYS = 30;

export const CATEGORIES: CategoryDef[] = [
  {
    label: 'Neu', tags: ['neu', 'new'], rotate: true,
    fallback: (r) => Boolean(r.created) && Date.now() - Date.parse(r.created!) < NEW_DAYS * 86_400_000,
  },
  {
    label: 'Favoriten', tags: ['favorit', 'favoriten', 'favorite', 'favourite', 'favorites', 'lieblingsrezept'],
    photo: 'Black Bean Enchiladas',
    fallback: (r) => (averageStars(r) ?? 0) >= 4,
  },
  { label: 'Schnell', tags: ['schnell', 'quick', 'fast', 'unter 30 min'], photo: 'Gorgonzola-Birne-Raddicio Farfalle' },
  { label: 'Backen', tags: ['backen', 'baking', 'gebäck', 'kuchen', 'brot'], photo: 'Französische Zitronen-tarte' },
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
const letters = (value: string) =>
  value.normalize('NFKD').replace(/\p{M}/gu, '').toLocaleLowerCase('de').replace(/[^\p{L}\p{N}]+/gu, '');

/** How alike two names are, 0 to 1, by shared letter pairs; small typos still score high. */
function similarity(a: string, b: string): number {
  const pairs = (s: string) => Array.from({ length: Math.max(0, s.length - 1) }, (_, i) => s.slice(i, i + 2));
  const left = pairs(a);
  const right = pairs(b);
  if (!left.length || !right.length) return a === b ? 1 : 0;
  const pool = [...right];
  let shared = 0;
  for (const pair of left) {
    const at = pool.indexOf(pair);
    if (at >= 0) {
      shared += 1;
      pool.splice(at, 1);
    }
  }
  return (2 * shared) / (left.length + right.length);
}

/** The recipe a category's `photo` names (name, link or Notion id), forgiving small typos. */
export function namedRecipe(recipes: Recipe[], wanted: string | undefined): Recipe | undefined {
  if (!wanted) return undefined;
  const target = plain(wanted);
  const exact = recipes.find((r) =>
    plain(r.name) === target || plain(r.id) === target || (r.source_url && plain(r.source_url) === target)
    || plain(r.notion_url).endsWith(target));
  if (exact) return exact;
  const name = letters(wanted);
  let best: { recipe: Recipe; score: number } | undefined;
  for (const recipe of recipes) {
    const score = similarity(letters(recipe.name), name);
    if (score >= 0.8 && (!best || score > best.score)) best = { recipe, score };
  }
  return best?.recipe;
}

export type Category = { key: string; label: string; emoji?: string; matches: (recipe: Recipe) => boolean; tags: string[] };

/** The categories that have recipes, in the fixed order, with the tags they cover. */
export function categories(recipes: Recipe[]): Category[] {
  const result: Category[] = [];
  for (const def of CATEGORIES) {
    const matches = categoryMatcher(def, recipes);
    if (!matches) continue;
    const tags = [...new Set(recipes.flatMap((r) => r.tags).filter((t) => def.tags.includes(key(t))))];
    // The emoji of its most used tag, e.g. 🇮🇹 for "🇮🇹 Italienisch" and "Italian".
    const counted = tags
      .map((t) => ({ t, n: recipes.filter((r) => r.tags.includes(t)).length }))
      .sort((a, b) => b.n - a.n);
    const own = counted.map(({ t }) => t.match(/^[^\p{L}\p{N}]+/u)?.[0].trim()).find(Boolean);
    result.push({ key: `kategorie:${def.label}`, label: def.label, emoji: own || tagEmoji(def.label), matches, tags });
  }
  return result;
}

function tagEmoji(label: string): string | undefined {
  return { Neu: '🌟', Favoriten: '❤️', Veggie: '🥬' }[label];
}

const newestFirst = (a: Recipe, b: Recipe) => (b.created || '').localeCompare(a.created || '');

/** The recipe whose photo each category shows: the chosen one, today's new one, or the first with a photo. */
export function categoryPhotos(recipes: Recipe[], today: Date): Map<string, Recipe> {
  const shown = categories(recipes);
  const photos = new Map<string, Recipe>();
  const used = new Set<string>();
  const take = (label: string, recipe: Recipe | undefined) => {
    if (!recipe) return;
    photos.set(label, recipe);
    used.add(recipe.id);
  };
  const defOf = (label: string) => CATEGORIES.find((d) => d.label === label)!;
  // Chosen photos first, so the automatic ones do not take them.
  for (const c of shown) {
    const chosen = namedRecipe(recipes, defOf(c.label).photo);
    if (chosen?.image) take(c.label, chosen);
  }
  for (const c of shown) {
    if (photos.has(c.label)) continue;
    const withPhoto = recipes.filter(c.matches).filter((r) => r.image).sort(newestFirst);
    const fresh = withPhoto.filter((r) => !used.has(r.id));
    const pool = fresh.length ? fresh : withPhoto;
    if (defOf(c.label).rotate && pool.length) {
      const day = Math.floor(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) / 86_400_000);
      take(c.label, pool[day % pool.length]);
    } else {
      take(c.label, pool[0] ?? recipes.filter(c.matches).sort(newestFirst)[0]);
    }
  }
  return photos;
}
