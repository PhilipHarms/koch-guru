import { useEffect, useLayoutEffect, useMemo, useState } from 'preact/hooks';
import type { Recipe } from '../lib/api';
import { useData } from '../lib/data';
import { recipePath, sourceOf } from '../lib/recipe';
import { averageStars, starsText } from '../lib/cooked';
import { load, save } from '../lib/storage';
import { queryWords, searchScore } from '../lib/search';
import { hasOwnEmoji, tagStyle } from '../lib/tiles';
import { categories } from '../lib/categories';
import { RecipeImage } from '../components/RecipeImage';
import { AufklappenIcon, KachelnIcon, KreuzIcon, ListeIcon, PlusIcon, SucheIcon } from '../components/icons';

type View = 'kacheln' | 'liste';
type Sort = 'neu' | 'name' | 'bewertung' | 'gekocht';
const SORTS = ['neu', 'name', 'bewertung', 'gekocht'] as const;
const SORT_LABEL: Record<Sort, string> = {
  neu: 'Neu hinzugefügt', name: 'Name', bewertung: 'Bewertung', gekocht: 'Zuletzt gekocht',
};

function compare(sort: Sort): (a: Recipe, b: Recipe) => number {
  const newest = (a: Recipe, b: Recipe) => (b.created || '').localeCompare(a.created || '');
  if (sort === 'name') return (a, b) => a.name.localeCompare(b.name, 'de');
  // Unrated and never cooked come last, newest first among them.
  if (sort === 'bewertung') return (a, b) => (averageStars(b) ?? -1) - (averageStars(a) ?? -1) || newest(a, b);
  if (sort === 'gekocht') return (a, b) => (b.last_cooked || '').localeCompare(a.last_cooked || '') || newest(a, b);
  return newest;
}

/** "★ 4,5" when rated: quiet proof for the order by rating. */
function StarsBadge({ recipe }: { recipe: Recipe }) {
  const stars = averageStars(recipe);
  return stars === null ? null : <span class="kg-sterne-klein">{starsText(stars)}</span>;
}

/** Search, filters and scroll position survive a visit to a recipe page and back. */
const remembered = { query: '', selected: [] as string[], scrollY: 0 };

/** Open the overview with this search, e.g. from the search on Heute. */
export function searchInRecipes(query: string): void {
  remembered.query = query;
  remembered.selected = [];
  remembered.scrollY = 0;
}

/** Open the overview filtered by one chip, e.g. a category on Heute. */
export function filterRecipesBy(key: string): void {
  remembered.query = '';
  remembered.selected = [key];
  remembered.scrollY = 0;
}

type Chip = { key: string; label: string; emoji?: string; matches: (r: Recipe) => boolean };

function buildChips(recipes: Recipe[]): Chip[] {
  const count = (values: string[]) => {
    const counts = new Map<string, number>();
    for (const value of values) counts.set(value, (counts.get(value) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'de'));
  };
  // The categories of Heute first, in their order; they cover their tags ("Italian" under "Italienisch").
  const fixed = categories(recipes);
  const covered = new Set(fixed.flatMap((c) => c.tags));
  const tags = count(recipes.flatMap((r) => r.tags).filter((t) => !covered.has(t))).map(([tag]) => ({
    key: `tag:${tag}`,
    label: tag,
    emoji: hasOwnEmoji(tag) ? undefined : tagStyle(tag)?.chip,
    matches: (r: Recipe) => r.tags.includes(tag),
  }));
  // Cookbooks and sources only when at least two recipes share them.
  const origins = count(recipes.flatMap((r) => r.origin))
    .filter(([, n]) => n >= 2)
    .map(([origin]) => ({
      key: `origin:${origin}`,
      label: origin,
      matches: (r: Recipe) => r.origin.includes(origin),
    }));
  return [...fixed.map(({ key, label, emoji, matches }) => ({ key, label, emoji, matches })), ...tags, ...origins];
}

function RecipeCard({ recipe }: { recipe: Recipe }) {
  const tag = recipe.tags.map(tagStyle).find(Boolean);
  return (
    <a class="kg-karte" href={recipePath(recipe)}>
      <RecipeImage recipe={recipe} size="karte">
        {tag && (
          <div class="kg-bild-oben kg-tags">
            <span class={`kg-tag ${tag.className}`}>{tag.label}</span>
          </div>
        )}
      </RecipeImage>
      <span class="titel-karte">{recipe.name}</span>
      <span class="quelle kg-karte-quelle">{sourceOf(recipe)} <StarsBadge recipe={recipe} /></span>
    </a>
  );
}

export function RecipeRow({ recipe }: { recipe: Recipe }) {
  return (
    <li>
      <a class="kg-zeile" href={recipePath(recipe)}>
        <RecipeImage recipe={recipe} size="liste" />
        <span class="kg-zeile-text">
          <span class="titel-karte">{recipe.name}</span>
          <span class="meta">{sourceOf(recipe)} <StarsBadge recipe={recipe} /></span>
        </span>
      </a>
    </li>
  );
}

export function RecipesRoute() {
  return <RecipesPage recipes={useData().recipes} />;
}

export function RecipesPage({ recipes }: { recipes: Recipe[] }) {
  const { people, cookedSupported } = useData();
  const sorts = SORTS.filter((s) => (s === 'bewertung' ? people.length > 0 : s === 'gekocht' ? cookedSupported : true));
  const [query, setQuery] = useState(remembered.query);
  const [selected, setSelected] = useState<string[]>(remembered.selected);

  useEffect(() => {
    remembered.query = query;
    remembered.selected = selected;
  }, [query, selected]);

  useLayoutEffect(() => {
    window.scrollTo(0, remembered.scrollY);
    return () => {
      remembered.scrollY = window.scrollY;
    };
  }, []);
  const [view, setView] = useState<View>(() => load('ansicht', ['kacheln', 'liste'] as const, 'kacheln'));
  const [sort, setSort] = useState<Sort>(() => load('sortierung', SORTS, 'neu'));

  const chips = useMemo(() => buildChips(recipes), [recipes]);

  const words = useMemo(() => queryWords(query), [query]);
  const searching = words.length > 0;

  const shown = useMemo(() => {
    const active = chips.filter((chip) => selected.includes(chip.key));
    const bySort = compare(sorts.includes(sort) ? sort : 'neu');
    const list = recipes
      .filter((r) => active.every((chip) => chip.matches(r)))
      .map((recipe) => ({ recipe, score: searching ? searchScore(recipe, words) : 1 }))
      .filter((hit) => hit.score > 0);
    // While searching, the best matches come first; the chosen order only breaks ties.
    return list.sort((a, b) => b.score - a.score || bySort(a.recipe, b.recipe)).map((hit) => hit.recipe);
  }, [recipes, words, searching, selected, chips, sort, sorts.join()]);

  const chooseView = (next: View) => {
    setView(next);
    save('ansicht', next);
  };
  const toggleSort = () => {
    const next: Sort = sorts[(sorts.indexOf(sort) + 1) % sorts.length];
    setSort(next);
    save('sortierung', next);
  };
  // One filter at a time: a tap selects it, a second tap shows all again.
  const toggleChip = (key: string) => setSelected((current) => (current.includes(key) ? [] : [key]));

  return (
    <main class="page rezepte-mit-knopf">
      <header class="page-header">
        <h1 class="titel-seite">Rezepte</h1>
        <p class="text-klein page-summary" aria-live="polite">
          {shown.length === recipes.length ? `${recipes.length} Rezepte` : `${shown.length} von ${recipes.length} Rezepten`}
        </p>
      </header>

      <div class="page-pad">
        <label class="kg-search" for="suche">
          <SucheIcon />
          <span class="kg-sr">Rezepte durchsuchen</span>
          <input id="suche" type="search" placeholder="Name oder Zutat, z. B. Kürbis" value={query}
            onInput={(e) => setQuery((e.target as HTMLInputElement).value)} autocomplete="off" />
          {query && (
            <button type="button" class="search-clear" aria-label="Suche leeren" onClick={() => setQuery('')}>
              <KreuzIcon size={18} />
            </button>
          )}
        </label>
      </div>

      {chips.length > 0 && (
        <div class="kg-chips chips-row" role="group" aria-label="Kategorien">
          <button type="button" class="kg-chip" aria-pressed={selected.length === 0} onClick={() => setSelected([])}>
            Alle
          </button>
          {chips.map((chip) => (
            <button type="button" class="kg-chip" key={chip.key} aria-pressed={selected.includes(chip.key)}
              onClick={() => toggleChip(chip.key)}>
              {chip.emoji && <span aria-hidden="true">{chip.emoji}</span>}
              {chip.label}
            </button>
          ))}
        </div>
      )}

      <div class="page-pad toolbar">
        {searching ? (
          <p class="sort-button">Beste Treffer zuerst</p>
        ) : (
          <button type="button" class="sort-button" onClick={toggleSort}>
            <span class="meta">Sortiert nach</span>
            {SORT_LABEL[sorts.includes(sort) ? sort : 'neu']}
            <AufklappenIcon size={18} />
          </button>
        )}
        <div class="kg-seg" role="group" aria-label="Ansicht">
          <button type="button" aria-pressed={view === 'kacheln'} aria-label="Kachelansicht" onClick={() => chooseView('kacheln')}>
            <KachelnIcon size={20} />
          </button>
          <button type="button" aria-pressed={view === 'liste'} aria-label="Listenansicht" onClick={() => chooseView('liste')}>
            <ListeIcon size={20} />
          </button>
        </div>
      </div>

      {shown.length === 0 ? (
        <p class="page-pad empty">Nichts gefunden. Probier einen anderen Begriff oder weniger Filter.</p>
      ) : view === 'kacheln' ? (
        <div class="kg-raster page-pad">
          {shown.map((r) => <RecipeCard recipe={r} key={r.id} />)}
        </div>
      ) : (
        <ul class="kg-liste page-pad">
          {shown.map((r) => <RecipeRow recipe={r} key={r.id} />)}
        </ul>
      )}
      <a class="kg-fab rezepte-neu" href="/rezepte/neu" aria-label="Rezept hinzufügen">
        <PlusIcon size={28} />
      </a>
    </main>
  );
}
