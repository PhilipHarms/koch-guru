import { useEffect, useMemo, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type ChatTurn, type Recipe, type Suggestions } from '../lib/api';
import { dailyPicks } from '../lib/daily';
import { useData } from '../lib/data';
import { messageOf, recipePath, sourceOf } from '../lib/recipe';
import { queryWords, searchScore } from '../lib/search';
import { hasOwnEmoji, tagStyle } from '../lib/tiles';
import { RecipeImage } from '../components/RecipeImage';
import { KreuzIcon, SucheIcon, WeiterIcon } from '../components/icons';
import { RecipeRow, searchInRecipes } from './Recipes';

const SEARCH_PREVIEW = 5;

/** Kept while the app is open, so the ideas are still there after looking at a recipe. */
const remembered = { query: '', pick: 0, wish: '', history: [] as ChatTurn[], ideas: null as Suggestions | null };

export function TodayRoute() {
  const { me, recipes } = useData();
  useEffect(() => window.scrollTo(0, 0), []);
  return (
    <main class="page heute">
      <header class="page-header heute-kopf">
        <h1 class="titel-heute">Was kochen wir heute?</h1>
        <span class="heute-avatar" aria-label={`Angemeldet als ${me.name}`}>{me.name.slice(0, 1).toLocaleUpperCase('de')}</span>
      </header>
      <Search recipes={recipes} />
      <DailySuggestion recipes={recipes} />
      <Ideas />
      <ThisWeek recipes={recipes} />
    </main>
  );
}

function Search({ recipes }: { recipes: Recipe[] }) {
  const { route } = useLocation();
  const [query, setQuery] = useState(remembered.query);
  useEffect(() => {
    remembered.query = query;
  }, [query]);

  const hits = useMemo(() => {
    const words = queryWords(query);
    if (!words.length) return [];
    return recipes
      .map((recipe) => ({ recipe, score: searchScore(recipe, words) }))
      .filter((hit) => hit.score > 0)
      .sort((a, b) => b.score - a.score || a.recipe.name.localeCompare(b.recipe.name, 'de'))
      .map((hit) => hit.recipe);
  }, [recipes, query]);

  const showAll = () => {
    searchInRecipes(query);
    route('/rezepte');
  };

  return (
    <section class="page-pad heute-suche" aria-label="Suche">
      <form role="search" onSubmit={(e) => { e.preventDefault(); if (hits.length) showAll(); }}>
        <label class="kg-search" for="suche-heute">
          <SucheIcon />
          <span class="kg-sr">Rezepte durchsuchen</span>
          <input id="suche-heute" type="search" placeholder="Rezept oder Zutat suchen" value={query} autocomplete="off"
            enterkeyhint="search" onInput={(e) => setQuery((e.target as HTMLInputElement).value)} />
          {query && (
            <button type="button" class="search-clear" aria-label="Suche leeren" onClick={() => setQuery('')}>
              <KreuzIcon size={18} />
            </button>
          )}
        </label>
      </form>
      {query.trim() && (
        <div class="heute-treffer" aria-live="polite">
          {hits.length === 0 ? (
            <p class="text-klein muted">Nichts gefunden.</p>
          ) : (
            <>
              <ul class="kg-liste">
                {hits.slice(0, SEARCH_PREVIEW).map((r) => <RecipeRow recipe={r} key={r.id} />)}
              </ul>
              {hits.length > SEARCH_PREVIEW && (
                <button type="button" class="rezept-link" onClick={showAll}>
                  Alle {hits.length} Treffer anzeigen <WeiterIcon size={18} />
                </button>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Tags({ recipe, max }: { recipe: Recipe; max: number }) {
  if (!recipe.tags.length) return null;
  return (
    <ul class="kg-tags rezept-tags" aria-label="Tags">
      {recipe.tags.slice(0, max).map((tag) => {
        const style = tagStyle(tag);
        const label = !hasOwnEmoji(tag) && style?.chip ? `${style.chip} ${tag}` : tag;
        return <li key={tag} class={`kg-tag ${style?.className ?? 'kg-tag-neutral'}`}>{label}</li>;
      })}
    </ul>
  );
}

function DailySuggestion({ recipes }: { recipes: Recipe[] }) {
  const picks = useMemo(() => dailyPicks(recipes, new Date()), [recipes]);
  const [index, setIndex] = useState(remembered.pick);
  useEffect(() => {
    remembered.pick = index;
  }, [index]);
  if (!picks.length) return null;
  const { recipe, reason } = picks[index % picks.length];

  return (
    <section class="heute-vorschlag" aria-labelledby="vorschlag-titel">
      <a href={recipePath(recipe)} class="heute-vorschlag-link">
        <RecipeImage recipe={recipe} size="vorschlag" />
        <div class="heute-vorschlag-karte">
          <p id="vorschlag-titel" class="meta heute-vorschlag-label">Vorschlag für heute</p>
          <h2 class="titel-rezept">{recipe.name}</h2>
          <p class="quelle rezept-quelle">{sourceOf(recipe)}</p>
          <Tags recipe={recipe} max={3} />
          <p class="heute-grund">{reason}</p>
        </div>
      </a>
      {picks.length > 1 && (
        <div class="page-pad heute-vorschlag-aktion">
          <button type="button" class="kg-btn kg-btn-sekundaer" onClick={() => setIndex((i) => i + 1)}>
            Anderer Vorschlag
          </button>
        </div>
      )}
    </section>
  );
}

function Ideas() {
  const [wish, setWish] = useState(remembered.wish);
  const [ideas, setIdeas] = useState<Suggestions | null>(remembered.ideas);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async (event: Event) => {
    event.preventDefault();
    const text = wish.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.suggest(text, remembered.history);
      // Follow-ups like "lieber ohne Fleisch" refer to the last answer.
      remembered.history = [
        ...remembered.history,
        { role: 'user' as const, content: text },
        { role: 'assistant' as const, content: result.history_entry },
      ].slice(-8);
      remembered.ideas = result;
      remembered.wish = '';
      setIdeas(result);
      setWish('');
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    remembered.history = [];
    remembered.ideas = null;
    setIdeas(null);
  };

  return (
    <section class="page-pad heute-ideen" aria-labelledby="ideen-titel">
      <div class="leer-box heute-ideen-box">
        <h2 id="ideen-titel" class="titel-block">Lust auf etwas Bestimmtes?</h2>
        <p class="text-klein">Schreib einen Wunsch, KochGuru sucht passende Rezepte aus eurer Sammlung.</p>
        <form class="heute-wunsch" onSubmit={ask}>
          <label class="kg-search" for="wunsch">
            <span class="kg-sr">Wunsch</span>
            <input id="wunsch" type="text" placeholder="z. B. schnell und ohne Fleisch" value={wish} maxLength={500}
              enterkeyhint="send" onInput={(e) => {
                const value = (e.target as HTMLInputElement).value;
                setWish(value);
                remembered.wish = value;
              }} />
          </label>
          <button type="submit" class="kg-btn kg-btn-primaer" disabled={busy || !wish.trim()}>
            {busy ? 'Sucht …' : 'Vorschläge holen'}
          </button>
        </form>
        {error && <p class="fehler" role="alert">{error}</p>}
      </div>
      {ideas && (
        <div class="heute-ideen-ergebnis" aria-live="polite">
          {ideas.message && <p class="text-klein">{ideas.message}</p>}
          {ideas.suggestions.length > 0 && (
            <ul class="kg-liste">
              {ideas.suggestions.map(({ recipe, reason }) => (
                <li key={recipe.id}>
                  <a class="kg-zeile" href={recipePath(recipe)}>
                    <RecipeImage recipe={recipe} size="liste" />
                    <span class="kg-zeile-text">
                      <span class="titel-karte">{recipe.name}</span>
                      <span class="meta heute-ideen-grund">{reason}</span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          )}
          <button type="button" class="rezept-link" onClick={reset}>Neue Suche</button>
        </div>
      )}
    </section>
  );
}

function ThisWeek({ recipes }: { recipes: Recipe[] }) {
  const planned = recipes.filter((r) => r.this_week);
  return (
    <section class="heute-woche" aria-labelledby="woche-titel">
      <div class="page-pad abschnitt-kopf">
        <h2 id="woche-titel" class="abschnitt">Diese Woche</h2>
        <a class="rezept-link" href="/woche">Alle anzeigen</a>
      </div>
      {planned.length === 0 ? (
        <p class="page-pad text-klein muted">Noch nichts geplant.</p>
      ) : (
        <ul class="heute-woche-reihe">
          {planned.map((recipe) => (
            <li key={recipe.id}>
              <a class="heute-woche-karte" href={recipePath(recipe)}>
                <RecipeImage recipe={recipe} size="woche-gross" />
                <span class="titel-karte">{recipe.name}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
