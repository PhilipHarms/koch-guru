import type { ComponentChildren } from 'preact';
import { useEffect, useRef, useState } from 'preact/hooks';
import { api, type Recipe, type ShoppingItem, type ShoppingList } from '../lib/api';
import { useData } from '../lib/data';
import { messageOf, recipePath, sameId } from '../lib/recipe';
import { load as loadChoice, save as saveChoice } from '../lib/storage';
import { RecipeImage } from '../components/RecipeImage';
import { AufklappenIcon, PlusIcon } from '../components/icons';

const VIEWS = ['rezept', 'abteilung'] as const;
type View = (typeof VIEWS)[number];
const VIEW_LABEL: Record<View, string> = { rezept: 'Rezept', abteilung: 'Abteilung' };
const NO_AISLE = 'Ohne Abteilung';
/** A ticked line stays where it is this long, so a wrong tap can be undone, then moves. */
const MOVE_DELAY_MS = 1200;

type Where = 'offen' | 'da';

/** One line per ingredient, with the amounts and recipes of all its lines. */
type AisleItem = ShoppingItem & { amounts: string[]; recipes: string[] };

function mergedItems(list: ShoppingList, planned: Recipe[]): AisleItem[] {
  const merged = new Map<string, AisleItem>();
  for (const group of list.groups) {
    const recipe = planned.find((r) => sameId(r.id, group.recipe_id));
    for (const item of group.items) {
      const entry = merged.get(item.id) ?? { ...item, amounts: [], recipes: [] };
      if (item.amount) entry.amounts.push(item.amount);
      if (recipe) entry.recipes.push(recipe.name);
      merged.set(item.id, entry);
    }
  }
  for (const item of list.extras) if (!merged.has(item.id)) merged.set(item.id, { ...item, amounts: [], recipes: [] });
  return [...merged.values()];
}

function byAisle(list: ShoppingList, items: AisleItem[]): { aisle: string; items: AisleItem[] }[] {
  const aisles = new Map<string, AisleItem[]>();
  for (const item of items) {
    const key = item.aisle ?? NO_AISLE;
    aisles.set(key, [...(aisles.get(key) ?? []), item]);
  }
  // The order of the tags in Notion, then other tags by name, items without one last.
  const rank = (aisle: string) => (aisle === NO_AISLE ? Infinity : list.aisles.indexOf(aisle) >= 0 ? list.aisles.indexOf(aisle) : list.aisles.length);
  return [...aisles.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b, 'de'))
    .map(([aisle, items]) => ({ aisle, items: items.sort((a, b) => a.name.localeCompare(b.name, 'de')) }));
}

type State = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; list: ShoppingList };

/** Set `done` on every line of this ingredient: it can stand under several recipes. */
function withDone(list: ShoppingList, id: string, done: boolean): ShoppingList {
  const mark = (item: ShoppingItem) => (item.id === id ? { ...item, done } : item);
  return {
    ...list,
    groups: list.groups.map((g) => ({ ...g, items: g.items.map(mark) })),
    extras: list.extras.map(mark),
  };
}

function openCount(list: ShoppingList): number {
  const open = new Set<string>();
  for (const item of [...list.groups.flatMap((g) => g.items), ...list.extras]) if (!item.done) open.add(item.id);
  return open.size;
}

export function ShoppingRoute() {
  const { recipes } = useData();
  const planned = recipes.filter((r) => r.this_week);
  const plannedKey = planned.map((r) => r.id).join(',');
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [hint, setHint] = useState<string | null>(null);
  const [view, setView] = useState<View>(() => loadChoice('einkauf-ansicht', VIEWS, 'rezept'));
  const [showDone, setShowDone] = useState(false);
  // Lines just ticked or unticked keep their place for a moment.
  const [pinned, setPinned] = useState<ReadonlyMap<string, Where>>(new Map());
  const timers = useRef(new Map<string, number>());

  const toggleView = () => {
    const next: View = view === 'rezept' ? 'abteilung' : 'rezept';
    setView(next);
    saveChoice('einkauf-ansicht', next);
  };

  useEffect(() => window.scrollTo(0, 0), []);
  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  const where = (item: ShoppingItem): Where => pinned.get(item.id) ?? (item.done ? 'da' : 'offen');
  const pin = (id: string, place: Where) => {
    setPinned((m) => new Map(m).set(id, place));
    window.clearTimeout(timers.current.get(id));
    timers.current.set(id, window.setTimeout(() => {
      timers.current.delete(id);
      setPinned((m) => {
        const next = new Map(m);
        next.delete(id);
        return next;
      });
    }, MOVE_DELAY_MS));
  };

  const load = async () => {
    try {
      setState({ kind: 'ready', list: await api.shoppingList() });
    } catch (error) {
      setState({ kind: 'error', message: messageOf(error) });
    }
  };

  // Load again when the week changes, e.g. after a recipe was added on another tab.
  useEffect(() => {
    load();
  }, [plannedKey]);

  if (state.kind === 'loading') {
    return (
      <Frame summary="">
        <p class="page-pad text-klein muted" aria-live="polite">Einkaufsliste wird geladen …</p>
      </Frame>
    );
  }
  if (state.kind === 'error') {
    return (
      <Frame summary="">
        <div class="page-pad">
          <div class="leer-box">
            <p class="text-klein">{state.message}</p>
            <button type="button" class="kg-btn kg-btn-sekundaer" onClick={() => { setState({ kind: 'loading' }); load(); }}>
              Nochmal versuchen
            </button>
          </div>
        </div>
      </Frame>
    );
  }

  const { list } = state;
  const change = (f: (list: ShoppingList) => ShoppingList) =>
    setState((s) => (s.kind === 'ready' ? { kind: 'ready', list: f(s.list) } : s));

  const toggle = async (item: ShoppingItem) => {
    const done = !item.done;
    setHint(null);
    pin(item.id, where(item));
    change((l) => withDone(l, item.id, done)); // show it at once, Notion follows
    try {
      await api.setBought(item.id, done);
    } catch (error) {
      change((l) => withDone(l, item.id, !done));
      setHint(messageOf(error));
    }
  };

  const added = (item: ShoppingItem) =>
    change((l) => (l.groups.some((g) => g.items.some((i) => i.id === item.id))
      ? withDone(l, item.id, false)
      : { ...l, extras: [...l.extras.filter((i) => i.id !== item.id), item] }));

  const missing = (item: ShoppingItem) => where(item) === 'offen';
  const linked = list.groups
    .map((g) => ({ ...g, recipe: planned.find((r) => sameId(r.id, g.recipe_id)) }))
    .filter((g): g is typeof g & { recipe: Recipe } => Boolean(g.recipe) && g.items.length > 0);
  const groups = linked
    .map((g) => ({ ...g, items: g.items.filter(missing) }))
    .filter((g) => g.items.length > 0);
  const extras = list.extras.filter(missing);
  const merged = mergedItems(list, planned);
  const aisles = view === 'abteilung' ? byAisle(list, merged.filter(missing)) : [];
  const atHome = merged.filter((item) => !missing(item)).sort((a, b) => a.name.localeCompare(b.name, 'de'));
  const shown = view === 'abteilung' ? aisles.length > 0 : groups.length > 0 || extras.length > 0;
  const open = openCount(list);
  const fromRecipes = planned.length === 1 ? 'Aus 1 Rezept dieser Woche' : `Aus ${planned.length} Rezepten dieser Woche`;
  const summary = planned.length === 0 && list.extras.length === 0
    ? 'Noch nichts geplant'
    : `${planned.length ? fromRecipes : 'Eigene Artikel'} · ${open === 0 ? 'alles erledigt' : `${open} offen`}`;

  return (
    <Frame summary={summary}>
      {hint && <p class="page-pad fehler" role="alert">{hint}</p>}
      {!list.can_check && (
        <p class="page-pad text-klein muted">
          Die Zutaten-Datenbank hat keine Checkbox „Bought“. Ohne sie lässt sich nichts abhaken.
        </p>
      )}

      {(linked.length > 0 || list.extras.length > 0) && (
        <div class="page-pad toolbar">
          <button type="button" class="sort-button" onClick={toggleView}>
            <span class="meta">Sortiert nach</span>
            {VIEW_LABEL[view]}
            <AufklappenIcon size={18} />
          </button>
        </div>
      )}

      {(linked.length > 0 || list.extras.length > 0) && !shown && (
        <p class="page-pad text-klein muted">Es fehlt nichts. Alles für die Rezepte der Woche ist da.</p>
      )}

      {planned.length === 0 && (
        <div class="page-pad">
          <div class="leer-box">
            <h2 class="titel-block">Noch keine Rezepte für diese Woche</h2>
            <p class="text-klein">Die Einkaufsliste füllt sich mit den Zutaten der Rezepte auf eurer Wochenliste.</p>
            <a class="kg-btn kg-btn-primaer" href="/rezepte">Zu den Rezepten</a>
          </div>
        </div>
      )}

      {view === 'abteilung' && aisles.map(({ aisle, items }) => (
        <section key={aisle} class="einkauf-gruppe page-pad" aria-label={aisle}>
          <h2 class="einkauf-kopf einkauf-abteilung">{aisle}</h2>
          <ul class="einkauf-liste">
            {items.map((item) => (
              <Line key={item.id} item={item} prefix={`abteilung-${aisle}`} disabled={!list.can_check} onToggle={toggle}
                amount={item.amounts.join(' + ') || null}
                note={item.recipes.length ? `für ${item.recipes.join(', ')}` : 'Eigener Artikel'} />
            ))}
          </ul>
        </section>
      ))}

      {view === 'rezept' && groups.map(({ recipe, items }) => (
        <section key={recipe.id} class="einkauf-gruppe page-pad" aria-label={recipe.name}>
          <h2 class="einkauf-kopf">
            <RecipeImage recipe={recipe} size="gruppe" />
            <a href={recipePath(recipe)}>{recipe.name}</a>
          </h2>
          <ul class="einkauf-liste">
            {items.map((item) => (
              <Line key={item.id} item={item} prefix={recipe.id} disabled={!list.can_check} onToggle={toggle} />
            ))}
          </ul>
        </section>
      ))}

      {planned.length > 0 && linked.length === 0 && (
        <p class="page-pad text-klein muted">
          Die Rezepte der Woche sind in Notion noch mit keinen Zutaten verknüpft.
        </p>
      )}

      {view === 'rezept' && extras.length > 0 && (
        <section class="einkauf-gruppe page-pad" aria-label="Eigene Artikel">
          <h2 class="einkauf-kopf">
            <span class="kg-bild kg-bild-gruppe einkauf-eigene" aria-hidden="true">🧺</span>
            <span>Eigene Artikel</span>
          </h2>
          <ul class="einkauf-liste">
            {extras.map((item) => (
              <Line key={item.id} item={item} prefix="eigene" disabled={!list.can_check} onToggle={toggle} />
            ))}
          </ul>
        </section>
      )}

      {list.can_add && <AddExtra onAdded={added} />}

      {atHome.length > 0 && (
        <section class="einkauf-gruppe page-pad einkauf-da" aria-label="Schon da">
          <button type="button" class="einkauf-da-kopf" aria-expanded={showDone} onClick={() => setShowDone(!showDone)}>
            <span>Schon da</span>
            <span class="einkauf-da-zahl">{atHome.length}</span>
            <AufklappenIcon size={20} />
          </button>
          {showDone && (
            <ul class="einkauf-liste">
              {atHome.map((item) => (
                <Line key={item.id} item={item} prefix="da" disabled={!list.can_check} onToggle={toggle}
                  amount={item.amounts.join(' + ') || null}
                  note={item.recipes.length ? `für ${item.recipes.join(', ')}` : 'Eigener Artikel'} />
              ))}
            </ul>
          )}
        </section>
      )}

    </Frame>
  );
}

function Frame({ summary, children }: { summary: string; children: ComponentChildren }) {
  return (
    <main class="page einkauf">
      <header class="page-header">
        <h1 class="titel-seite">Einkaufsliste</h1>
        <p class="text-klein page-summary" aria-live="polite">{summary}</p>
      </header>
      {children}
    </main>
  );
}

type LineProps = {
  item: ShoppingItem;
  prefix: string;
  disabled: boolean;
  onToggle: (item: ShoppingItem) => void;
  /** Overrides for the aisle view: all amounts, and the recipes it is for. */
  amount?: string | null;
  note?: string;
};

function Line({ item, prefix, disabled, onToggle, amount = item.amount, note }: LineProps) {
  const hint = note ?? (item.also.length > 0 ? `auch für ${item.also.join(', ')}` : null);
  const id = `einkauf-${prefix}-${item.id}`;
  const isImage = item.icon?.startsWith('http') || item.icon?.startsWith('/');
  return (
    <li>
      <label class="kg-check" for={id}>
        <input id={id} type="checkbox" checked={item.done} disabled={disabled} onChange={() => onToggle(item)} />
        <span class="kg-check-emoji" aria-hidden="true">
          {item.icon && isImage ? <img src={item.icon} alt="" width={24} height={24} loading="lazy" /> : (item.icon ?? initialOf(item.name))}
        </span>
        <span class="kg-check-text">
          <span class="kg-check-name">{item.name}</span>
          {hint && <span class="kg-check-fuer">{hint}</span>}
        </span>
        {amount && <span class="kg-check-menge">{amount}</span>}
      </label>
    </li>
  );
}

function AddExtra({ onAdded }: { onAdded: (item: ShoppingItem) => void }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: Event) => {
    event.preventDefault();
    const value = name.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      onAdded(await api.addExtra(value));
      setName('');
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form class="page-pad einkauf-eigener" onSubmit={submit}>
      <div class="einkauf-eingabe">
        <label class="kg-search">
          <span class="kg-sr">Eigenen Artikel hinzufügen</span>
          <input type="text" value={name} maxLength={100} placeholder="Eigener Artikel, z. B. Spülmittel"
            enterkeyhint="done" onInput={(e) => setName((e.target as HTMLInputElement).value)} />
        </label>
        <button type="submit" class="einkauf-plus" aria-label="Artikel hinzufügen" disabled={busy || !name.trim()}>
          <PlusIcon size={22} />
        </button>
      </div>
      {error && <p class="fehler" role="alert">{error}</p>}
    </form>
  );
}

/** Without an emoji or icon in Notion, the first letter fills the tile. */
function initialOf(name: string): string {
  return name.match(/\p{L}/u)?.[0].toLocaleUpperCase('de') ?? '·';
}
