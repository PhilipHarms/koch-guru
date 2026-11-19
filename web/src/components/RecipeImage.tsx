import type { ComponentChildren } from 'preact';
import { useState } from 'preact/hooks';
import type { Recipe } from '../lib/api';
import { emojiOf, tileOf } from '../lib/tiles';

type Size = 'karte' | 'liste' | 'woche' | 'woche-gross' | 'hero' | 'vorschlag' | 'gruppe' | 'kreis';

/** Cover photo from Notion, or the emoji tile. The tile stays underneath while the photo loads or if it fails. */
export function RecipeImage({ recipe, size, children }: { recipe: Recipe; size: Size; children?: ComponentChildren }) {
  const [failed, setFailed] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<string | null>(null);
  const showPhoto = recipe.image && failed !== recipe.image;
  return (
    <div class={`kg-bild kg-bild-${size} kg-bild-${tileOf(recipe)}`}>
      <span class="kg-bild-emoji" aria-hidden="true">{emojiOf(recipe)}</span>
      {showPhoto && (
        // Shown once complete: a photo that builds up line by line looks broken on a slow connection.
        <img src={recipe.image!} alt="" loading={size === 'hero' || size === 'vorschlag' ? 'eager' : 'lazy'} decoding="async"
          class={loaded === recipe.image ? 'geladen' : undefined}
          ref={(el) => { if (el?.complete && el.naturalWidth && loaded !== recipe.image) setLoaded(recipe.image); }}
          onLoad={() => setLoaded(recipe.image)} onError={() => setFailed(recipe.image)} />
      )}
      {children}
    </div>
  );
}
