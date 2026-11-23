import { useState } from 'preact/hooks';
import { api, type Recipe } from '../lib/api';
import { useData } from '../lib/data';
import { messageOf } from '../lib/recipe';
import { Stars } from './Stars';

/**
 * "Wie war's?": your stars and a note; it goes into the "Kochprotokoll" with today's date.
 * `later`: noted afterwards, not at the end of the cooking mode; the week is what counts.
 */
export function CookedSheet({ recipe, later = false, onCancel, onSaved }: {
  recipe: Recipe;
  later?: boolean;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { me, people, updateRecipe } = useData();
  const [stars, setStars] = useState(recipe.ratings?.[me.name] ?? 0);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canRate = people.includes(me.name);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      updateRecipe(await api.cooked(recipe.id, {
        stars: canRate && stars ? stars : null,
        note: note.trim() || null,
        ...(later ? { later: true } : {}),
      }));
      onSaved();
    } catch (err) {
      setError(messageOf(err));
      setSaving(false);
    }
  };

  return (
    <>
    <div class="blatt-hintergrund" aria-hidden="true" onClick={saving ? undefined : onCancel} />
    <section class="kochmodus-alle kochmodus-gekocht" role="dialog" aria-modal="true" aria-labelledby="gekocht-titel">
      <h2 id="gekocht-titel" class="titel-block">Wie war's?</h2>
      {canRate && (
        <div class="gekocht-sterne">
          <span class="text-klein muted">Deine Sterne</span>
          <Stars value={stars} person={me.name} onPick={setStars} disabled={saving} size={38} />
        </div>
      )}
      <label class="gekocht-notiz">
        <span class="text-klein muted">Notiz für nächstes Mal (optional)</span>
        <textarea rows={3} maxLength={500} value={note} placeholder="z. B. mehr Chili, weniger Salz"
          onInput={(e) => setNote((e.target as HTMLTextAreaElement).value)} />
      </label>
      {error && <p class="fehler" role="alert">{error}</p>}
      <div class="knopf-reihe">
        <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer" disabled={saving} onClick={save}>
          {saving ? 'Speichert …' : 'Speichern'}
        </button>
        <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer" disabled={saving} onClick={onCancel}>
          Abbrechen
        </button>
      </div>
    </section>
    </>
  );
}
