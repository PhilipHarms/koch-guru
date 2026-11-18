import type { Recipe } from './api';

/** Tile colours from the design system (tile-*), picked to fit the dish. */
const TILE_BY_EMOJI: Record<string, string> = {
  '🥗': 'blau', '🥒': 'gruen', '🥬': 'gruen', '🥦': 'gruen', '🫛': 'gruen', '🌿': 'gruen', '🍠': 'gruen', '🥑': 'gruen',
  '🍝': 'gelb', '🍞': 'gelb', '🥐': 'gelb', '🧀': 'gelb', '🍳': 'gelb', '🥚': 'gelb', '🥧': 'gelb', '🍕': 'gelb', '🥟': 'gelb',
  '🍆': 'flieder', '🫐': 'flieder', '🍇': 'flieder', '🍷': 'flieder', '🟣': 'flieder',
  '🐟': 'blau', '🦐': 'blau', '🍣': 'blau', '🥶': 'blau', '🍜': 'blau',
  '🍛': 'pfirsich', '🎃': 'pfirsich', '🥕': 'pfirsich', '🍅': 'pfirsich', '🌶️': 'pfirsich', '🍲': 'pfirsich', '🥘': 'pfirsich', '🍗': 'pfirsich',
};
const TILES = ['gruen', 'gelb', 'flieder', 'blau', 'pfirsich'];

export function tileOf(recipe: Recipe): string {
  if (recipe.emoji && TILE_BY_EMOJI[recipe.emoji]) return TILE_BY_EMOJI[recipe.emoji];
  let hash = 0;
  for (const char of recipe.id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return TILES[hash % TILES.length];
}

export function emojiOf(recipe: Recipe): string {
  return recipe.emoji || '🍽️';
}

/** Category tags with their own pill colours in the design system. */
const TAG_STYLE: Record<string, { label: string; className: string; chip?: string }> = {
  veggie: { label: 'Veggie', className: 'kg-tag-veggie', chip: '🥬' },
  vegetarisch: { label: 'Veggie', className: 'kg-tag-veggie', chip: '🥬' },
  winter: { label: 'Winter', className: 'kg-tag-winter', chip: '🍂' },
  new: { label: 'Neu', className: 'kg-tag-neu', chip: '🌟' },
  neu: { label: 'Neu', className: 'kg-tag-neu', chip: '🌟' },
};

/** Notion tags often start with their own emoji ("🥬 Veggie"); compare without it. */
export function tagWord(tag: string): string {
  return tag.replace(/^[^\p{L}\p{N}]+/u, '').trim();
}

export function hasOwnEmoji(tag: string): boolean {
  return tagWord(tag) !== tag.trim();
}

export function tagStyle(tag: string) {
  return TAG_STYLE[tagWord(tag).toLocaleLowerCase('de')];
}
