import type { ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { api, type Recipe, type ShoppingItem, type ShoppingList } from '../lib/api';
import { useData } from '../lib/data';
import { messageOf, recipePath, sameId } from '../lib/recipe';
import { load as loadChoice, save as saveChoice } from '../lib/storage';
import { RecipeImage } from '../components/RecipeImage';
import { PlusIcon } from '../components/icons';

const FILTERS = ['alle', 'fehlend', 'lager'] as const;
type Filter = (typeof FILTERS)[number];
const FILTER_LABEL: Record<Filter, string> = { alle: 'Alle', fehlend: 'Fehlend', lager: 'Auf Lager' };

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
  const [filter, setFilter] = useState<Filter>(() => loadChoice('einkauf-filter', FILTERS, 'fehlend'));
  // Lines ticked or unticked here stay in view until the filter changes, so a wrong tap can be undone.
  const [touched, setTouched] = useState<ReadonlySet<string>>(new Set());

  const chooseFilter = (next: Filter) => {
    setFilter(next);
    setTouched(new Set());
    saveChoice('einkauf-filter', next);
  };

  useEffect(() => window.scrollTo(0, 0), []);

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
    setTouched((t) => new Set(t).add(item.id));
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

  const visible = (item: ShoppingItem) =>
    filter === 'alle' || touched.has(item.id) || (filter === 'fehlend' ? !item.done : item.done);
  const linked = list.groups
    .map((g) => ({ ...g, recipe: planned.find((r) => sameId(r.id, g.recipe_id)) }))
    .filter((g): g is typeof g & { recipe: Recipe } => Boolean(g.recipe) && g.items.length > 0);
  const groups = linked
    .map((g) => ({ ...g, items: g.items.filter(visible) }))
    .filter((g) => g.items.length > 0);
  const extras = list.extras.filter(visible);
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
        <div class="page-pad">
          <div class="kg-seg kg-seg-voll einkauf-filter" role="group" aria-label="Zutaten zeigen">
            {FILTERS.map((f) => (
              <button key={f} type="button" aria-pressed={filter === f} onClick={() => chooseFilter(f)}>
                {FILTER_LABEL[f]}
              </button>
            ))}
          </div>
        </div>
      )}

      {(linked.length > 0 || list.extras.length > 0) && groups.length === 0 && extras.length === 0 && (
        <p class="page-pad text-klein muted">
          {filter === 'fehlend' ? 'Es fehlt nichts. Alles für die Rezepte der Woche ist da.' : 'Noch nichts auf Lager.'}
        </p>
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

      {groups.map(({ recipe, items }) => (
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

      {extras.length > 0 && (
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

type LineProps = { item: ShoppingItem; prefix: string; disabled: boolean; onToggle: (item: ShoppingItem) => void };

function Line({ item, prefix, disabled, onToggle }: LineProps) {
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
          {item.also.length > 0 && <span class="kg-check-fuer">auch für {item.also.join(', ')}</span>}
        </span>
        {item.amount && <span class="kg-check-menge">{item.amount}</span>}
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
