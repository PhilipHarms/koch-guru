import type { Recipe } from '../lib/api';
import { emojiOf, tileOf } from '../lib/tiles';

type Size = 'karte' | 'liste' | 'woche';

/** Photo or emoji tile. Photos follow in a later step; until then every recipe shows its emoji. */
export function RecipeImage({ recipe, size, children }: { recipe: Recipe; size: Size; children?: preact.ComponentChildren }) {
  return (
    <div class={`kg-bild kg-bild-${size} kg-bild-${tileOf(recipe)}`}>
      <span class="kg-bild-emoji" aria-hidden="true">{emojiOf(recipe)}</span>
      {children}
    </div>
  );
}
