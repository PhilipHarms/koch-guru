import { useState } from 'preact/hooks';
import type { Recipe } from '../lib/api';
import { CookedSheet } from './CookedSheet';

/**
 * Before a recipe leaves the week list without the cooking mode: was it cooked?
 * "Ja" goes on to "Wie war's?"; `onDecided` then takes it off the list. Cancel leaves everything as it was.
 */
export function AskCookedSheet({ recipe, onCancel, onDecided }: {
  recipe: Recipe;
  onCancel: () => void;
  onDecided: () => void;
}) {
  const [rating, setRating] = useState(false);
  if (rating) return <CookedSheet recipe={recipe} onCancel={onCancel} onSaved={onDecided} />;
  return (
    <>
      <div class="blatt-hintergrund" aria-hidden="true" onClick={onCancel} />
      <section class="kochmodus-alle kochmodus-gekocht" role="dialog" aria-modal="true" aria-labelledby="gekocht-frage">
        <h2 id="gekocht-frage" class="titel-block">Habt ihr „{recipe.name}“ gekocht?</h2>
        <p class="text-klein muted gekocht-frage-text">Dann trägt KochGuru es als gekocht ein und du kannst es bewerten.</p>
        <div class="gekocht-frage-knoepfe">
          <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer" onClick={() => setRating(true)}>
            Ja, gekocht
          </button>
          <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer" onClick={onDecided}>
            Nein, nur entfernen
          </button>
        </div>
      </section>
    </>
  );
}
