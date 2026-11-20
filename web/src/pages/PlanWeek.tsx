import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type WeekSuggestion } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf } from '../lib/recipe';
import { RecipeImage } from '../components/RecipeImage';
import { KreuzIcon, UhrIcon } from '../components/icons';

/** Dishes KochGuru plans for a week; fewer when some are already on the list, but always a few. */
const WEEK_SIZE = 5;
const AT_LEAST = 2;
const EXCLUDE_MAX = 100; // what the server takes

type Phase = 'loading' | 'review' | 'swapping' | 'saving' | 'error';

/** "Woche planen": KochGuru suggests dishes for the week; the ticked ones go on the week list. */
export function PlanWeekPage() {
  const { recipes, weekSupported, updateRecipe } = useData();
  const { route } = useLocation();
  // Fixed when the screen opens; adding to the list here must not change it.
  const [count] = useState(() => Math.max(AT_LEAST, WEEK_SIZE - recipes.filter((r) => r.this_week).length));
  const [phase, setPhase] = useState<Phase>('loading');
  const [ideas, setIdeas] = useState<WeekSuggestion[]>([]);
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const shown = useRef<string[]>([]); // every idea so far, so "andere Vorschläge" brings new ones
  const alive = useRef(true);

  const load = async () => {
    setPhase('loading');
    setError(null);
    try {
      const { suggestions } = await api.planWeek({ count });
      if (!alive.current) return;
      shown.current = suggestions.map((s) => s.recipe.id);
      setIdeas(suggestions);
      setChosen(new Set(shown.current));
      setPhase('review');
    } catch (e) {
      if (!alive.current) return;
      setError(messageOf(e));
      setPhase('error');
    }
  };

  useEffect(() => {
    window.scrollTo(0, 0);
    alive.current = true;
    if (weekSupported) load();
    return () => { alive.current = false; };
  }, []);

  const leave = () => (canGoBack() ? window.history.back() : route('/woche', true));
  const toggle = (id: string) =>
    setChosen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const picked = ideas.filter((i) => chosen.has(i.recipe.id));
  const unpicked = ideas.filter((i) => !chosen.has(i.recipe.id));

  /** New ideas in the places of the unticked ones; the ticked ones stay. */
  const swap = async () => {
    setPhase('swapping');
    setError(null);
    setNote(null);
    try {
      const { suggestions } = await api.planWeek({
        count: unpicked.length,
        keep: picked.map((i) => i.recipe.id),
        exclude: shown.current.slice(-EXCLUDE_MAX),
      });
      if (!alive.current) return;
      shown.current = [...shown.current, ...suggestions.map((s) => s.recipe.id)];
      const fresh = [...suggestions];
      setIdeas(ideas.flatMap((idea) => (chosen.has(idea.recipe.id) ? [idea] : fresh.length ? [fresh.shift()!] : [])));
      setChosen((s) => new Set([...s, ...suggestions.map((i) => i.recipe.id)]));
      if (suggestions.length < unpicked.length) {
        setNote(suggestions.length === 0
          ? 'Mehr passende Rezepte hat KochGuru gerade nicht.'
          : 'Mehr passende Rezepte hat KochGuru gerade nicht, deshalb sind es jetzt weniger.');
      }
    } catch (e) {
      if (alive.current) setError(messageOf(e));
    } finally {
      if (alive.current) setPhase('review');
    }
  };

  const save = async () => {
    setPhase('saving');
    setError(null);
    const saved = new Set<string>();
    try {
      for (const idea of picked) {
        updateRecipe(await api.setThisWeek(idea.recipe.id, true));
        saved.add(idea.recipe.id);
      }
      route('/woche', true);
    } catch (e) {
      // What is on the list stays there and leaves this screen; the button then sends only the rest.
      setIdeas((current) => current.filter((i) => !saved.has(i.recipe.id)));
      setError(`${saved.size ? `${saved.size} sind schon auf der Wochenliste. ` : ''}${messageOf(e)}`);
      setPhase('review');
    }
  };

  const busy = phase === 'swapping' || phase === 'saving';
  const saveLabel = phase === 'saving'
    ? 'Wird eingetragen …'
    : picked.length === 0 ? 'Nichts ausgewählt' : `${picked.length} auf die Wochenliste`;

  return (
    <main class="page planen">
      <header class="page-header import-kopf">
        <h1 class="titel-seite">Woche planen</h1>
        <button type="button" class="kg-iconbtn" aria-label="Schließen" onClick={leave}>
          <KreuzIcon size={20} />
        </button>
      </header>

      {!weekSupported ? (
        <p class="page-pad text-klein muted">
          Die Notion-Datenbank hat keine Checkbox „This Week?“. Ohne sie gibt es keine Wochenliste.
        </p>
      ) : phase === 'loading' ? (
        <div class="page-pad planen-inhalt" aria-busy="true">
          <p class="text-klein" role="status">KochGuru stellt deine Woche zusammen …</p>
          <ul class="planen-liste" aria-hidden="true">
            {Array.from({ length: count }, (_, i) => (
              <li key={i} class="planen-zeile planen-platzhalter">
                <span class="planen-label">
                  <span class="kg-bild kg-bild-woche" />
                  <span class="planen-text"><span class="planen-strich" /><span class="planen-strich kurz" /></span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : phase === 'error' ? (
        <div class="page-pad planen-inhalt">
          <p class="fehler" role="alert">{error}</p>
          <div class="knopf-reihe">
            <button type="button" class="kg-btn kg-btn-primaer" onClick={load}>Nochmal versuchen</button>
          </div>
        </div>
      ) : ideas.length === 0 ? (
        <div class="page-pad planen-inhalt">
          <p class="text-klein muted">
            {note ?? 'KochGuru hat gerade keine Vorschläge. Alles, was passt, steht schon auf der Wochenliste oder war vor Kurzem dran.'}
          </p>
          <a class="kg-btn kg-btn-primaer" href="/woche">Zur Wochenliste</a>
        </div>
      ) : (
        <div class="page-pad planen-inhalt">
          <p class="text-klein muted">
            Abwechslungsreich, passend zur Jahreszeit, mit Lieblingen und lange nicht Gekochtem. Hak ab, was diese
            Woche passt.
          </p>

          <ul class={`planen-liste${phase === 'swapping' ? ' planen-tauscht' : ''}`} aria-busy={phase === 'swapping'}>
            {ideas.map(({ recipe, reason, quick }) => {
              const on = chosen.has(recipe.id);
              const id = `planen-${recipe.id}`;
              return (
                <li key={recipe.id} class={`planen-zeile${on ? '' : ' planen-aus'}`}>
                  <label class="planen-label" for={id}>
                    <RecipeImage recipe={recipe} size="woche" />
                    <span class="planen-text">
                      <span class="titel-karte">{recipe.name}</span>
                      <span class="planen-grund">{reason}</span>
                      {quick && <span class="planen-schnell"><UhrIcon size={14} /> Schnell gemacht</span>}
                    </span>
                    <input id={id} type="checkbox" checked={on} disabled={busy} onChange={() => toggle(recipe.id)} />
                  </label>
                </li>
              );
            })}
          </ul>

          {note && <p class="text-klein muted" role="status">{note}</p>}
          {error && <p class="fehler" role="alert">{error}</p>}

          {unpicked.length > 0 && (
            <button type="button" class="kg-btn kg-btn-sekundaer planen-tauschen" disabled={busy} onClick={swap}>
              {phase === 'swapping'
                ? 'Sucht andere …'
                : unpicked.length === 1 ? '1 anderer Vorschlag' : `${unpicked.length} andere Vorschläge`}
            </button>
          )}

          <div class="fotos-leiste">
            <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer" onClick={save}
              disabled={busy || picked.length === 0}>
              {saveLabel}
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
