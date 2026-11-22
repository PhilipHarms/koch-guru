import { useEffect, useState } from 'preact/hooks';
import { api, type Recipe } from '../lib/api';
import { useData } from '../lib/data';
import { messageOf, recipePath, sourceOf } from '../lib/recipe';
import { cookedLabel, cookedThisWeek } from '../lib/cooked';
import { AskCookedSheet } from '../components/AskCookedSheet';
import { RecipeImage } from '../components/RecipeImage';
import { KreuzIcon } from '../components/icons';

export function WeekRoute() {
  const { recipes, weekSupported, cookedSupported, updateRecipe, weekCleared } = useData();
  const planned = recipes.filter((r) => r.this_week);
  // Without the cooking mode nobody noted that these were cooked; leaving the list, they get asked about.
  const unsure = cookedSupported ? planned.filter((r) => !cookedThisWeek(r)) : [];
  const [busy, setBusy] = useState<string | null>(null); // recipe id, or "alle"
  const [confirming, setConfirming] = useState(false);
  const [asking, setAsking] = useState<Recipe | null>(null);
  const [cookedOnes, setCookedOnes] = useState<ReadonlySet<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => window.scrollTo(0, 0), []);

  const run = async (key: string, action: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  };

  const takeOff = (recipe: Recipe) => run(recipe.id, async () => updateRecipe(await api.setThisWeek(recipe.id, false)));
  const remove = (recipe: Recipe) => (unsure.includes(recipe) ? setAsking(recipe) : takeOff(recipe));
  const toggleCooked = (id: string) =>
    setCookedOnes((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const clear = () =>
    run('alle', async () => {
      // Marked cooked, they leave the list right away; clearing takes the rest.
      for (const recipe of unsure.filter((r) => cookedOnes.has(r.id))) {
        updateRecipe(await api.cooked(recipe.id, {}));
      }
      await api.clearWeek();
      weekCleared();
      setConfirming(false);
      setCookedOnes(new Set());
    });

  const summary = planned.length === 0
    ? 'Noch nichts geplant'
    : planned.length === 1 ? '1 Rezept geplant' : `${planned.length} Rezepte geplant`;

  return (
    <main class="page">
      <header class="page-header">
        <h1 class="titel-seite">Diese Woche</h1>
        <p class="text-klein page-summary" aria-live="polite">{weekSupported ? summary : ''}</p>
      </header>

      {!weekSupported ? (
        <p class="page-pad text-klein muted">
          Die Notion-Datenbank hat keine Checkbox „This Week?“. Ohne sie gibt es keine Wochenliste.
        </p>
      ) : planned.length === 0 ? (
        <div class="page-pad">
          <div class="leer-box">
            <h2 class="titel-block">Noch nichts geplant</h2>
            <p class="text-klein">Lass dir von KochGuru eine Woche vorschlagen oder such selbst Rezepte aus.</p>
            <div class="knopf-reihe">
              <a class="kg-btn kg-btn-primaer" href="/woche/planen">Woche planen</a>
              <a class="kg-btn kg-btn-sekundaer" href="/rezepte">Zu den Rezepten</a>
            </div>
          </div>
        </div>
      ) : (
        <>
          <ul class="woche-liste page-pad">
            {planned.map((recipe) => (
              <li key={recipe.id} class="woche-eintrag">
                <a class="woche-link" href={recipePath(recipe)}>
                  <RecipeImage recipe={recipe} size="woche" />
                  <span class="woche-text">
                    <span class="titel-karte">{recipe.name}</span>
                    {cookedSupported && cookedThisWeek(recipe) ? (
                      <span class="meta woche-gekocht">{cookedLabel(recipe.last_cooked!)}</span>
                    ) : (
                      <span class="meta muted">{sourceOf(recipe)}</span>
                    )}
                  </span>
                </a>
                <button type="button" class="kg-iconbtn woche-entfernen" disabled={busy !== null}
                  aria-label={`${recipe.name} von der Wochenliste nehmen`} onClick={() => remove(recipe)}>
                  <KreuzIcon size={18} />
                </button>
              </li>
            ))}
          </ul>

          <div class="page-pad woche-ende">
            {confirming ? (
              <div class="leer-box" role="group" aria-label="Wochenliste leeren">
                <p class="text-klein">
                  {planned.length === 1 ? 'Das Rezept' : `Alle ${planned.length} Rezepte`} von der Wochenliste nehmen?
                </p>
                {unsure.length > 0 && (
                  <fieldset class="woche-gekocht-wahl" disabled={busy !== null}>
                    <legend class="text-klein muted">
                      {unsure.length === 1 ? 'Habt ihr das gekocht?' : 'Was davon habt ihr gekocht?'} Abgehaktes wird als gekocht eingetragen.
                    </legend>
                    {unsure.map((recipe) => (
                      <label key={recipe.id}>
                        <input type="checkbox" checked={cookedOnes.has(recipe.id)} onChange={() => toggleCooked(recipe.id)} />
                        {recipe.name}
                      </label>
                    ))}
                  </fieldset>
                )}
                <div class="knopf-reihe">
                  <button type="button" class="kg-btn kg-btn-primaer" disabled={busy !== null} onClick={clear}>
                    Ja, leeren
                  </button>
                  <button type="button" class="kg-btn kg-btn-sekundaer" disabled={busy !== null} onClick={() => setConfirming(false)}>
                    Abbrechen
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" class="kg-btn kg-btn-sekundaer" disabled={busy !== null} onClick={() => setConfirming(true)}>
                Wochenliste leeren
              </button>
            )}
          </div>

          <div class="page-pad">
            {planned.length === 1 ? (
              <div class="leer-box">
                <h2 class="titel-block">Nur noch ein Rezept geplant</h2>
                <p class="text-klein">Lass dir von KochGuru die nächste Woche vorschlagen oder such selbst Rezepte aus.</p>
                <div class="knopf-reihe">
                  <a class="kg-btn kg-btn-primaer" href="/woche/planen">Woche planen</a>
                  <a class="kg-btn kg-btn-sekundaer" href="/rezepte">Zu den Rezepten</a>
                </div>
              </div>
            ) : (
              <div class="leer-box">
                <h2 class="titel-block">Noch ein Abend frei?</h2>
                <p class="text-klein">Lass dir von KochGuru etwas vorschlagen oder such selbst ein Rezept aus.</p>
                <div class="knopf-reihe">
                  <a class="kg-btn kg-btn-primaer" href="/woche/planen">Ideen holen</a>
                  <a class="kg-btn kg-btn-sekundaer" href="/rezepte">Zu den Rezepten</a>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {error && <p class="page-pad fehler" role="alert">{error}</p>}

      {asking && (
        <AskCookedSheet recipe={asking} onCancel={() => setAsking(null)} onCooked={() => setAsking(null)}
          onRemoveOnly={() => { setAsking(null); takeOff(asking); }} />
      )}
    </main>
  );
}
