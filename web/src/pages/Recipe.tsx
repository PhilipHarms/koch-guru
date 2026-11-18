import { Fragment, type ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type Block, type GeneratedIngredient, type GeneratedRecipe, type Recipe, type RecipeContent, type TextRun } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf, sameId, sourceLink, sourceOf } from '../lib/recipe';
import { hasOwnEmoji, tagStyle } from '../lib/tiles';
import { RecipeImage } from '../components/RecipeImage';
import { ExternIcon, HakenIcon, PortionenIcon, UhrIcon, WocheIcon, ZurueckIcon } from '../components/icons';
import { PlaceholderPage } from './Placeholder';

type Loadable<T> = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; value: T };

export function RecipeRoute({ id }: { id: string }) {
  const { recipes } = useData();
  const recipe = recipes.find((r) => sameId(r.id, id));
  if (!recipe) return <PlaceholderPage title="Nicht gefunden" text="Dieses Rezept gibt es nicht mehr in Notion." />;
  return <RecipePage recipe={recipe} />;
}

function RecipePage({ recipe }: { recipe: Recipe }) {
  const { weekSupported, updateRecipe } = useData();
  const { route } = useLocation();
  const [content, setContent] = useState<Loadable<RecipeContent>>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [weekError, setWeekError] = useState<string | null>(null);
  const [notCreated, setNotCreated] = useState<string[]>([]);

  useEffect(() => window.scrollTo(0, 0), [recipe.id]);

  useEffect(() => {
    let active = true;
    setContent({ kind: 'loading' });
    api.content(recipe.id).then(
      (value) => active && setContent({ kind: 'ready', value }),
      (error) => active && setContent({ kind: 'error', message: messageOf(error) }),
    );
    return () => {
      active = false;
    };
  }, [recipe.id, attempt]);

  const goBack = () => (canGoBack() ? window.history.back() : route('/rezepte', true));

  const toggleWeek = async () => {
    setSaving(true);
    setWeekError(null);
    try {
      updateRecipe(await api.setThisWeek(recipe.id, !recipe.this_week));
    } catch (error) {
      setWeekError(messageOf(error));
    } finally {
      setSaving(false);
    }
  };

  const ready = content.kind === 'ready' ? content.value : null;
  const link = sourceLink(recipe);

  return (
    <main class="rezept">
      <div class="rezept-hero">
        <RecipeImage recipe={recipe} size="hero" />
        <button type="button" class="kg-iconbtn kg-iconbtn-schwebend rezept-zurueck" aria-label="Zurück" onClick={goBack}>
          <ZurueckIcon />
        </button>
      </div>

      <div class="rezept-inhalt">
        <header class="rezept-kopf">
          <h1 class="titel-rezept">{recipe.name}</h1>
          <p class="quelle rezept-quelle">{sourceOf(recipe)}</p>
          {ready && (ready.minutes || ready.servings) ? (
            <p class="meta rezept-meta">
              {ready.minutes ? <span><UhrIcon size={18} />{ready.minutes} Min.</span> : null}
              {ready.servings ? (
                <span><PortionenIcon size={18} />{/^\d+$/.test(ready.servings) ? `${ready.servings} Portionen` : ready.servings}</span>
              ) : null}
            </p>
          ) : null}
          {recipe.tags.length > 0 && (
            <ul class="kg-tags rezept-tags" aria-label="Tags">
              {recipe.tags.map((tag) => {
                const style = tagStyle(tag);
                const label = !hasOwnEmoji(tag) && style?.chip ? `${style.chip} ${tag}` : tag;
                return <li key={tag} class={`kg-tag ${style?.className ?? 'kg-tag-neutral'}`}>{label}</li>;
              })}
            </ul>
          )}
        </header>

        <div class="rezept-aktionen">
          {weekSupported && (
            <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer rezept-woche" aria-pressed={recipe.this_week}
              disabled={saving} onClick={toggleWeek}>
              {recipe.this_week ? <HakenIcon size={20} /> : <WocheIcon size={20} />}
              {recipe.this_week ? 'Steht auf der Wochenliste' : 'Auf die Wochenliste'}
            </button>
          )}
          {weekError && <p class="fehler" role="alert">{weekError}</p>}
          <div class="rezept-links">
            {link && (
              <a class="rezept-link" href={link} target="_blank" rel="noopener noreferrer">
                <ExternIcon size={18} />Originalrezept
              </a>
            )}
            <a class="rezept-link" href={recipe.notion_url} target="_blank" rel="noopener noreferrer">
              <ExternIcon size={18} />In Notion
            </a>
          </div>
        </div>

        {content.kind === 'loading' && <p class="text-klein muted" aria-live="polite">Rezept wird geladen …</p>}
        {content.kind === 'error' && (
          <div class="leer-box" role="alert">
            <p class="text-klein">{content.message}</p>
            <button type="button" class="kg-btn kg-btn-sekundaer" onClick={() => setAttempt((n) => n + 1)}>Nochmal laden</button>
          </div>
        )}
        {ready && <Ingredients content={ready} />}
        {notCreated.length > 0 && (
          <p class="text-klein hinweis" role="status">
            Rezept gespeichert, aber nicht verknüpft: {notCreated.join(', ')}. Dafür braucht KochGuru in Notion
            Schreibrechte auf die Zutaten-Datenbank.
          </p>
        )}
        {ready && (
          <Steps recipe={recipe} content={ready} link={link} onGenerated={(missing) => {
            setNotCreated(missing);
            setAttempt((n) => n + 1);
          }} />
        )}
        {ready && ready.blocks.length > 0 && (
          <section class="rezept-abschnitt notizen" aria-label="Weitere Inhalte aus Notion">
            {ready.blocks[0].type !== 'heading' && <h2 class="abschnitt">Notizen</h2>}
            <Blocks blocks={ready.blocks} />
          </section>
        )}
      </div>
    </main>
  );
}

function Ingredients({ content }: { content: RecipeContent }) {
  const count = content.ingredients.filter((i) => !('group' in i)).length;
  return (
    <section class="rezept-abschnitt" aria-labelledby="zutaten-titel">
      <div class="abschnitt-kopf">
        <h2 id="zutaten-titel" class="abschnitt">Zutaten</h2>
        {count > 0 && <p class="meta muted">{count === 1 ? '1 Zutat' : `${count} Zutaten`}</p>}
      </div>
      {count === 0 ? (
        <p class="text-klein muted">In Notion sind keine Zutaten eingetragen.</p>
      ) : (
        <ul class="zutaten">
          {content.ingredients.map((item, index) =>
            'group' in item ? (
              <li key={index} class="zutaten-gruppe overline">{item.group}</li>
            ) : (
              <li key={index} class="zutat">
                <span class="zutat-emoji" aria-hidden="true">
                  {item.emoji ?? (item.icon ? <img src={item.icon} alt="" width={24} height={24} loading="lazy" /> : initialOf(item.name))}
                </span>
                <span class="zutat-text">
                  <span class="zutat-name">{item.name}</span>
                  {item.amount && <span class="meta muted">{item.amount}</span>}
                </span>
              </li>
            ),
          )}
        </ul>
      )}
    </section>
  );
}

/** Without an emoji or icon in Notion, the ingredient's first letter fills the tile. */
function initialOf(name: string): string {
  return name.match(/\p{L}/u)?.[0].toLocaleUpperCase('de') ?? '·';
}

type StepsProps = { recipe: Recipe; content: RecipeContent; link: string | null; onGenerated: (notCreated: string[]) => void };

function Steps({ recipe, content, link, onGenerated }: StepsProps) {
  let number = 0;
  // Notes or photos on the Notion page are a source too, e.g. when the link is Instagram.
  const hasNotes = content.blocks.length > 0;
  return (
    <section class="rezept-abschnitt" aria-labelledby="zubereitung-titel">
      <h2 id="zubereitung-titel" class="abschnitt">Zubereitung</h2>
      {content.steps.length === 0 ? (
        <Generate recipe={recipe} link={link} canGenerate={Boolean(link) || hasNotes} onSaved={onGenerated} />
      ) : (
        <ol class="schritte">
          {content.steps.map((step, index) => {
            if ('group' in step) return <li key={index} class="schritte-gruppe overline">{step.group}</li>;
            number += 1;
            return (
              <li key={index} class="schritt">
                <span class="schritt-nummer" aria-hidden="true">{number}</span>
                <p class="fliesstext">{step.text}</p>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

// --- Rezept generieren -----------------------------------------------------------------

type GenerateState =
  | { kind: 'idle' }
  | { kind: 'reading' }
  | { kind: 'preview'; value: GeneratedRecipe; include: boolean[]; saving: boolean }
  | { kind: 'error'; message: string };

function statusText(item: GeneratedIngredient, include: boolean): string {
  if (item.status === 'linked') return 'schon verknüpft';
  if (!include) return item.staple ? 'immer da, wird nicht verknüpft' : 'wird nicht verknüpft';
  return item.status === 'existing' ? `verknüpft mit „${item.zutat}“` : `wird als „${item.zutat}“ neu angelegt`;
}

function Generate({ recipe, link, canGenerate, onSaved }: {
  recipe: Recipe;
  link: string | null;
  canGenerate: boolean;
  onSaved: (notCreated: string[]) => void;
}) {
  const { updateRecipe } = useData();
  const [state, setState] = useState<GenerateState>({ kind: 'idle' });

  const read = async () => {
    setState({ kind: 'reading' });
    try {
      const value = await api.generate(recipe.id);
      setState({ kind: 'preview', value, include: value.ingredients.map((i) => i.include), saving: false });
    } catch (error) {
      setState({ kind: 'error', message: messageOf(error) });
    }
  };

  if (state.kind === 'idle' || state.kind === 'error') {
    return (
      <div class="leer-box">
        <p class="text-klein">In Notion stehen noch keine Schritte.</p>
        {canGenerate && (
          <p class="text-klein muted">
            KochGuru kann Zutaten und Schritte {link ? 'aus dem Originalrezept' : 'aus den Notizen und Fotos in Notion'} holen, auf Deutsch.
            Du siehst sie vorher, gespeichert wird erst auf deinen Wunsch.
          </p>
        )}
        {state.kind === 'error' && <p class="fehler" role="alert">{state.message}</p>}
        {canGenerate && (
          <button type="button" class="kg-btn kg-btn-primaer" onClick={read}>
            {state.kind === 'error' ? 'Nochmal versuchen' : 'Rezept generieren'}
          </button>
        )}
        {link && (
          <a class="rezept-link" href={link} target="_blank" rel="noopener noreferrer">
            <ExternIcon size={18} />Im Originalrezept nachlesen
          </a>
        )}
      </div>
    );
  }

  if (state.kind === 'reading') {
    return (
      <div class="leer-box" aria-live="polite">
        <p class="text-klein">KochGuru liest das Rezept. Das dauert etwa eine halbe Minute …</p>
      </div>
    );
  }

  const { value, include, saving } = state;
  const toggle = (index: number) =>
    setState({ ...state, include: include.map((on, i) => (i === index ? !on : on)) });

  const save = async () => {
    setState({ ...state, saving: true });
    try {
      const result = await api.saveGenerated(recipe.id, {
        url: value.url,
        servings: value.servings,
        minutes: value.minutes,
        steps: value.steps,
        ingredients: value.ingredients.map((item, i) => ({
          line: item.line, zutat: item.zutat, emoji: item.emoji, link: include[i] && item.status !== 'linked',
        })),
      });
      updateRecipe(result.recipe);
      onSaved(result.not_created);
    } catch (error) {
      setState({ kind: 'error', message: messageOf(error) });
    }
  };

  let host = 'der Notion-Seite';
  if (value.url) {
    try {
      host = new URL(value.url).hostname.replace(/^www\./, '');
    } catch {
      host = value.url;
    }
  }

  return (
    <div class="generiert" aria-live="polite">
      <p class="meta muted">Vorschau aus {host}, noch nicht gespeichert</p>
      <div class="abschnitt-kopf">
        <h3 class="titel-block">Zutaten</h3>
        {value.servings && <p class="meta muted">{value.servings}</p>}
      </div>
      <p class="text-klein muted">Angehakte Zutaten werden mit eurer Zutaten-Datenbank verknüpft und landen damit auf der Einkaufsliste.</p>
      <ul class="zutaten">
        {value.ingredients.map((item, index) => (
          <li key={index} class="zutat generiert-zutat">
            <label>
              <input type="checkbox" checked={include[index]} disabled={item.status === 'linked' || saving}
                onChange={() => toggle(index)} />
              <span class="zutat-emoji" aria-hidden="true">{item.emoji ?? initialOf(item.name)}</span>
              <span class="zutat-text">
                <span class="zutat-name">{item.name}</span>
                {item.amount && <span class="meta muted">{item.amount}</span>}
                <span class={`meta generiert-status generiert-${include[index] ? item.status : 'aus'}`}>
                  {statusText(item, include[index])}
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <h3 class="titel-block">Zubereitung</h3>
      {value.steps.length ? (
        <ol class="schritte">
          {value.steps.map((step, index) => (
            <li key={index} class="schritt">
              <span class="schritt-nummer" aria-hidden="true">{index + 1}</span>
              <p class="fliesstext">{step}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p class="text-klein muted">Auf der Quelle stehen keine Schritte.</p>
      )}
      <div class="knopf-reihe">
        <button type="button" class="kg-btn kg-btn-primaer" disabled={saving} onClick={save}>
          {saving ? 'Speichert …' : 'In Notion speichern'}
        </button>
        <button type="button" class="kg-btn kg-btn-sekundaer" disabled={saving} onClick={() => setState({ kind: 'idle' })}>
          Verwerfen
        </button>
      </div>
    </div>
  );
}

// --- Other Notion content -------------------------------------------------------------

function Runs({ runs }: { runs: TextRun[] }) {
  return (
    <>
      {runs.map((run, index) => {
        let node: ComponentChildren = run.text;
        if (run.bold) node = <strong>{node}</strong>;
        if (run.italic) node = <em>{node}</em>;
        return run.href ? (
          <a key={index} href={run.href} target="_blank" rel="noopener noreferrer">{node}</a>
        ) : (
          <Fragment key={index}>{node}</Fragment>
        );
      })}
    </>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function Blocks({ blocks }: { blocks: Block[] }) {
  const out: ComponentChildren[] = [];
  for (let i = 0; i < blocks.length; ) {
    const block = blocks[i];
    if (block.type === 'bullet' || block.type === 'number') {
      const items = [];
      while (i < blocks.length && blocks[i].type === block.type) items.push(blocks[i++] as typeof block);
      const List = block.type === 'bullet' ? 'ul' : 'ol';
      out.push(
        <List key={i} class="notiz-liste fliesstext">
          {items.map((item, n) => (
            <li key={n}>
              <Runs runs={item.text} />
              {item.children && <Blocks blocks={item.children} />}
            </li>
          ))}
        </List>,
      );
      continue;
    }
    out.push(<BlockView key={i} block={block} />);
    i += 1;
  }
  return <>{out}</>;
}

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case 'heading':
      return block.level === 3
        ? <h3 class="titel-block notiz-titel"><Runs runs={block.text} /></h3>
        : <h2 class="abschnitt notiz-titel"><Runs runs={block.text} /></h2>;
    case 'paragraph':
      return <p class="fliesstext notiz-text"><Runs runs={block.text} /></p>;
    case 'quote':
      return <blockquote class="fliesstext notiz-zitat"><Runs runs={block.text} /></blockquote>;
    case 'callout':
      return (
        <div class="notiz-hinweis fliesstext">
          {block.emoji && <span aria-hidden="true">{block.emoji}</span>}
          <div><Runs runs={block.text} />{block.children && <Blocks blocks={block.children} />}</div>
        </div>
      );
    case 'toggle':
      return (
        <details class="notiz-aufklapp fliesstext">
          <summary><Runs runs={block.text} /></summary>
          {block.children && <Blocks blocks={block.children} />}
        </details>
      );
    case 'todo':
      return (
        <p class={`fliesstext notiz-todo${block.checked ? ' erledigt' : ''}`}>
          <span class="notiz-kasten" aria-hidden="true">{block.checked && <HakenIcon size={14} />}</span>
          <span class="kg-sr">{block.checked ? 'Erledigt: ' : 'Offen: '}</span>
          <Runs runs={block.text} />
        </p>
      );
    case 'image':
      return (
        <figure class="notiz-bild">
          <img src={block.url} alt={block.caption || 'Foto aus Notion'} loading="lazy" decoding="async" />
          {block.caption && <figcaption class="meta muted">{block.caption}</figcaption>}
        </figure>
      );
    case 'link':
      return (
        <a class="notiz-link" href={block.url} target="_blank" rel="noopener noreferrer">
          <ExternIcon size={18} />
          <span>{block.caption || hostOf(block.url)}</span>
        </a>
      );
    case 'divider':
      return <hr class="notiz-trenner" />;
    default:
      return null;
  }
}
