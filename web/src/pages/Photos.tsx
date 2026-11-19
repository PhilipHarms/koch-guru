import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type Recipe } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf, recipePath } from '../lib/recipe';
import { KreuzIcon } from '../components/icons';

const BATCH = 8; // pages looked up per request
const SAVE_BATCH = 25;

type Phase = 'loading' | 'searching' | 'review' | 'saving' | 'done' | 'error';

/** "Fotos nachholen": the photo of the linked page as cover for recipes without one, after a look. */
export function PhotosPage() {
  const { updateRecipe } = useData();
  const { route } = useLocation();
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<Recipe[]>([]);
  const [withoutLink, setWithoutLink] = useState(0);
  const [found, setFound] = useState<ReadonlyMap<string, string | null>>(new Map());
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [broken, setBroken] = useState<ReadonlySet<string>>(new Set());
  const [result, setResult] = useState<{ saved: number; failed: string[] } | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    window.scrollTo(0, 0);
    alive.current = true;
    (async () => {
      try {
        const missing = await api.missingPhotos();
        if (!alive.current) return;
        setCandidates(missing.with_link);
        setWithoutLink(missing.without_link);
        setPhase('searching');
        for (let i = 0; i < missing.with_link.length && alive.current; i += BATCH) {
          const batch = missing.with_link.slice(i, i + BATCH).map((r) => r.id);
          let answers: { id: string; image: string | null }[];
          try {
            answers = await api.findPhotos(batch);
          } catch {
            answers = batch.map((id) => ({ id, image: null })); // one failed batch does not stop the rest
          }
          if (!alive.current) return;
          setFound((m) => {
            const next = new Map(m);
            answers.forEach((a) => next.set(a.id, a.image));
            return next;
          });
          setChosen((s) => {
            const next = new Set(s);
            answers.forEach((a) => a.image && next.add(a.id));
            return next;
          });
        }
        if (alive.current) setPhase('review');
      } catch (e) {
        if (!alive.current) return;
        setError(messageOf(e));
        setPhase('error');
      }
    })();
    return () => { alive.current = false; };
  }, []);

  const leave = () => (canGoBack() ? window.history.back() : route('/rezepte', true));
  const toggle = (id: string) =>
    setChosen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const markBroken = (id: string) => {
    setBroken((s) => new Set(s).add(id));
    setChosen((s) => {
      const next = new Set(s);
      next.delete(id);
      return next;
    });
  };

  const withPhoto = candidates.filter((r) => found.get(r.id));
  const noPhoto = phase === 'review' || phase === 'saving' || phase === 'done'
    ? candidates.filter((r) => found.has(r.id) && !found.get(r.id))
    : [];
  const selected = withPhoto.filter((r) => chosen.has(r.id) && !broken.has(r.id));

  const save = async () => {
    setPhase('saving');
    setError(null);
    let saved = 0;
    const failed: string[] = [];
    try {
      for (let i = 0; i < selected.length; i += SAVE_BATCH) {
        const items = selected.slice(i, i + SAVE_BATCH).map((r) => ({ id: r.id, image: found.get(r.id)! }));
        const answer = await api.applyPhotos(items);
        answer.recipes.forEach(updateRecipe);
        saved += answer.recipes.length;
        failed.push(...answer.failed);
      }
      setResult({ saved, failed });
      setPhase('done');
    } catch (e) {
      // What was saved stays saved; the rest can be tried again.
      setError(`${saved ? `${saved} Fotos sind gespeichert. ` : ''}${messageOf(e)}`);
      setPhase('review');
    }
  };

  return (
    <main class="page fotos">
      <header class="page-header import-kopf">
        <h1 class="titel-seite">Fotos nachholen</h1>
        <button type="button" class="kg-iconbtn" aria-label="Schließen" onClick={leave}>
          <KreuzIcon size={20} />
        </button>
      </header>

      {phase === 'loading' && <p class="page-pad text-klein muted">Einen Moment …</p>}
      {phase === 'error' && <p class="page-pad fehler" role="alert">{error}</p>}

      {phase === 'done' && result && (
        <div class="page-pad import-fertig" role="status">
          <h2 class="titel-block">{result.saved === 1 ? '1 Titelbild gespeichert' : `${result.saved} Titelbilder gespeichert`}</h2>
          {result.failed.length > 0 && (
            <p class="text-klein hinweis">Nicht gespeichert: {result.failed.join(', ')}.</p>
          )}
          <a class="kg-btn kg-btn-gross kg-btn-primaer" href="/rezepte">Zu den Rezepten</a>
        </div>
      )}

      {(phase === 'searching' || phase === 'review' || phase === 'saving') && (
        <div class="page-pad fotos-inhalt">
          {candidates.length === 0 ? (
            <p class="text-klein muted">Alle Rezepte mit Link haben schon ein Titelbild.</p>
          ) : (
            <p class="text-klein muted">
              {candidates.length === 1 ? '1 Rezept hat' : `${candidates.length} Rezepte haben`} einen Link, aber kein
              Titelbild. KochGuru holt das Foto der Rezeptseite. Übernommen wird nur, was angehakt ist.
            </p>
          )}
          {phase === 'searching' && (
            <p class="text-klein" aria-live="polite">Sucht Fotos … {found.size} von {candidates.length}</p>
          )}

          {withPhoto.length > 0 && (
            <ul class="fotos-raster">
              {withPhoto.map((recipe) => (
                <li key={recipe.id} class={`fotos-karte${chosen.has(recipe.id) && !broken.has(recipe.id) ? '' : ' fotos-aus'}`}>
                  <label>
                    <span class="fotos-bild">
                      {broken.has(recipe.id) ? (
                        <span class="fotos-kaputt text-klein">Bild lädt nicht</span>
                      ) : (
                        <img src={found.get(recipe.id)!} alt="" loading="lazy" referrerpolicy="no-referrer"
                          onError={() => markBroken(recipe.id)} />
                      )}
                      <input type="checkbox" checked={chosen.has(recipe.id) && !broken.has(recipe.id)}
                        disabled={broken.has(recipe.id) || phase === 'saving'} onChange={() => toggle(recipe.id)}
                        aria-label={`Foto für ${recipe.name} übernehmen`} />
                    </span>
                    <span class="fotos-name">{recipe.name}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}

          {noPhoto.length > 0 && (
            <details class="fotos-ohne">
              <summary class="text-klein">Kein Foto gefunden ({noPhoto.length})</summary>
              <ul>
                {noPhoto.map((recipe) => (
                  <li key={recipe.id} class="text-klein">
                    <a href={`${recipePath(recipe)}/bearbeiten`}>{recipe.name}</a>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {phase !== 'searching' && withoutLink > 0 && (
            <p class="text-klein muted">
              {withoutLink === 1 ? '1 weiteres Rezept hat' : `${withoutLink} weitere Rezepte haben`} keinen Link. Dort
              lädst du ein eigenes Foto über den Stift auf dem Rezept hoch.
            </p>
          )}

          {error && <p class="fehler" role="alert">{error}</p>}
          {candidates.length > 0 && (
            <div class="fotos-leiste">
              <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer" onClick={save}
                disabled={phase !== 'review' || selected.length === 0}>
                {phase === 'saving' ? 'Speichert …' : phase === 'searching' ? 'Sucht noch …'
                  : selected.length === 1 ? '1 Foto übernehmen' : `${selected.length} Fotos übernehmen`}
              </button>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
