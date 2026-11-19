import { useEffect, useMemo, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type Recipe } from '../lib/api';
import { dailyPicks, type DailyPick } from '../lib/daily';
import { useData } from '../lib/data';
import { messageOf, recipePath, sourceOf } from '../lib/recipe';
import { queryWords, searchScore } from '../lib/search';
import { hasOwnEmoji, tagStyle } from '../lib/tiles';
import { CATEGORIES, categoryMatcher, namedRecipe } from '../lib/categories';
import { averageStars } from '../lib/cooked';
import { RecipeImage } from '../components/RecipeImage';
import { KreuzIcon, PlusIcon, SucheIcon, WeiterIcon } from '../components/icons';
import { RecipeRow, searchInRecipes, showCategory } from './Recipes';

const SEARCH_PREVIEW = 5;

/** Kept while the app is open, so the ideas are still there after looking at a recipe. */
const remembered = { query: '', pick: 0 };

export function TodayRoute() {
  const { me, recipes } = useData();
  // Picked once per visit, so adding a recipe to the week does not reshuffle the screen.
  const [picks] = useState(() => dailyPicks(recipes, new Date()));
  const [index, setIndex] = useState(remembered.pick);
  useEffect(() => {
    remembered.pick = index;
  }, [index]);
  useEffect(() => window.scrollTo(0, 0), []);
  const today = picks.length ? picks[index % picks.length] : null;

  return (
    <main class="page heute">
      <header class="page-header heute-kopf">
        <h1 class="titel-heute">Was kochen wir heute?</h1>
        <span class="heute-avatar" aria-label={`Angemeldet als ${me.name}`}>{me.name.slice(0, 1).toLocaleUpperCase('de')}</span>
      </header>
      <Search recipes={recipes} />
      {today && <DailySuggestion pick={today} canSwitch={picks.length > 1} onNext={() => setIndex((i) => i + 1)} />}
      <Categories recipes={recipes} />
      <ThisWeek recipes={recipes} picks={picks} exclude={today?.recipe.id} />
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

function DailySuggestion({ pick, canSwitch, onNext }: { pick: DailyPick; canSwitch: boolean; onNext: () => void }) {
  const { recipe, reason } = pick;
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
      {canSwitch && (
        <div class="page-pad heute-vorschlag-aktion">
          <button type="button" class="kg-btn kg-btn-sekundaer" onClick={onNext}>
            Anderer Vorschlag
          </button>
        </div>
      )}
    </section>
  );
}

type Category = { label: string; recipe: Recipe; matches: (recipe: Recipe) => boolean };

/** The fixed categories that have recipes, each with its chosen photo or one of its recipes. */
function categoriesOf(recipes: Recipe[]): Category[] {
  const used = new Set<string>();
  const categories: Category[] = [];
  for (const def of CATEGORIES) {
    const matches = categoryMatcher(def, recipes);
    if (!matches) continue;
    const matching = recipes.filter(matches);
    // The chosen photo; else a recipe with a photo, the best rated first, each only once.
    const ranked = [...matching].sort((a, b) =>
      Number(Boolean(b.image)) - Number(Boolean(a.image))
      || (averageStars(b) ?? 0) - (averageStars(a) ?? 0)
      || (b.created || '').localeCompare(a.created || ''));
    const recipe = namedRecipe(recipes, def.photo) ?? ranked.find((r) => !used.has(r.id)) ?? ranked[0];
    used.add(recipe.id);
    categories.push({ label: def.label, recipe, matches });
  }
  return categories;
}

function Categories({ recipes }: { recipes: Recipe[] }) {
  const categories = useMemo(() => categoriesOf(recipes), [recipes]);
  if (categories.length === 0) return null;
  return (
    <section class="heute-kategorien" aria-labelledby="kategorien-titel">
      <div class="page-pad abschnitt-kopf">
        <h2 id="kategorien-titel" class="abschnitt">Worauf habt ihr Lust?</h2>
      </div>
      <ul class="heute-kategorien-reihe">
        {categories.map(({ label, recipe, matches }) => (
          <li key={label}>
            <a class="heute-kategorie" href="/rezepte" onClick={() => showCategory(label, matches)}>
              <RecipeImage recipe={recipe} size="kreis" />
              <span class="heute-kategorie-name">{label}</span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

const WEEK_IDEAS = 4;

/** Below this many planned recipes, Heute suggests more for the week. */
const FEW_PLANNED = 2;

function ThisWeek({ recipes, picks, exclude }: { recipes: Recipe[]; picks: DailyPick[]; exclude?: string }) {
  const { weekSupported, updateRecipe } = useData();
  const planned = recipes.filter((r) => r.this_week);
  // Decided when the screen opens, so the ideas do not vanish while you add them.
  const [suggesting] = useState(() => weekSupported && planned.length < FEW_PLANNED);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const planNow = (id: string) => recipes.find((r) => r.id === id)?.this_week ?? false;
  const candidates = picks.filter((p) => p.recipe.id !== exclude && !planNow(p.recipe.id));
  const shown = candidates.length
    ? Array.from({ length: Math.min(WEEK_IDEAS, candidates.length) }, (_, i) => candidates[(offset + i) % candidates.length])
    : [];

  const add = async (recipe: Recipe) => {
    setBusy(recipe.id);
    setError(null);
    try {
      updateRecipe(await api.setThisWeek(recipe.id, true));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(null);
    }
  };

  const hint = planned.length === 0
    ? 'Noch nichts geplant. Wie wär’s damit?'
    : planned.length === 1
      ? 'Nur noch ein Rezept geplant. Ideen für die nächsten Abende:'
      : 'Noch mehr Ideen für die Woche:';

  return (
    <section class="heute-woche" aria-labelledby="woche-titel">
      <div class="page-pad abschnitt-kopf">
        <h2 id="woche-titel" class="abschnitt">Diese Woche</h2>
        <a class="rezept-link" href="/woche">Alle anzeigen</a>
      </div>
      {planned.length === 0 && !suggesting && <p class="page-pad text-klein muted">Noch nichts geplant.</p>}
      {planned.length > 0 && (
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
      {suggesting && shown.length > 0 && (
        <div class="page-pad heute-woche-ideen">
          <p class="text-klein">{hint}</p>
          <ul class="kg-liste">
            {shown.map(({ recipe, reason }) => (
              <li key={recipe.id} class="heute-woche-idee">
                <a class="kg-zeile" href={recipePath(recipe)}>
                  <RecipeImage recipe={recipe} size="liste" />
                  <span class="kg-zeile-text">
                    <span class="titel-karte">{recipe.name}</span>
                    <span class="meta heute-ideen-grund">{reason}</span>
                  </span>
                </a>
                <button type="button" class="kg-iconbtn" disabled={busy !== null} onClick={() => add(recipe)}
                  aria-label={`${recipe.name} auf die Wochenliste`}>
                  <PlusIcon size={20} />
                </button>
              </li>
            ))}
          </ul>
          {error && <p class="fehler" role="alert">{error}</p>}
          {candidates.length > WEEK_IDEAS && (
            <button type="button" class="rezept-link" onClick={() => setOffset((o) => o + WEEK_IDEAS)}>
              Andere Ideen
            </button>
          )}
        </div>
      )}
    </section>
  );
}
