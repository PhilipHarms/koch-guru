import { Fragment, type ComponentChildren } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type Block, type GeneratedRecipe, type Recipe, type RecipeContent, type TextRun } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf, recipePath, sameId, sourceLink, sourceOf } from '../lib/recipe';
import { hasOwnEmoji, tagStyle } from '../lib/tiles';
import { cookedLabel, cookedThisWeek } from '../lib/cooked';
import { stepLinks } from '../lib/stepLinks';
import { chooseServings, chosenServings, scaleAmount, servingsCount } from '../lib/portions';
import { Stars } from '../components/Stars';
import { AskCookedSheet } from '../components/AskCookedSheet';
import { RecipeImage } from '../components/RecipeImage';
import { IngredientChoice, initialOf } from '../components/IngredientChoice';
import { ExternIcon, GekochtIcon, StiftIcon, HakenIcon, KochenIcon, MinusIcon, NeuIcon, PlusIcon, PortionenIcon, UhrIcon, WocheIcon, ZurueckIcon } from '../components/icons';
import { shortName } from './Cook';
import { PlaceholderPage } from './Placeholder';

type Loadable<T> = { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; value: T };

export function RecipeRoute({ id }: { id: string }) {
  const { recipes } = useData();
  const recipe = recipes.find((r) => sameId(r.id, id));
  if (!recipe) return <PlaceholderPage title="Nicht gefunden" text="Dieses Rezept gibt es nicht mehr in Notion." />;
  return <RecipePage recipe={recipe} />;
}

function RecipePage({ recipe }: { recipe: Recipe }) {
  const { weekSupported, cookedSupported, updateRecipe } = useData();
  const { route } = useLocation();
  const [content, setContent] = useState<Loadable<RecipeContent>>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const [askingCooked, setAskingCooked] = useState(false);
  const [weekError, setWeekError] = useState<string | null>(null);
  const [notCreated, setNotCreated] = useState<string[]>([]);
  const [chosen, setChosen] = useState<number | null>(() => chosenServings(recipe.id));
  const choose = (servings: number | null) => {
    chooseServings(recipe.id, servings);
    setChosen(servings);
  };

  useEffect(() => window.scrollTo(0, 0), [recipe.id]);

  useEffect(() => {
    let active = true;
    setContent({ kind: 'loading' });
    api.content(recipe.id).then(
      (value) => {
        if (!active) return;
        setContent({ kind: 'ready', value });
        // Ask ahead what each step uses, so the cooking mode has it when it opens.
        if (value.steps.some((step) => 'text' in step)) stepLinks(recipe.id, value).catch(() => {});
      },
      (error) => active && setContent({ kind: 'error', message: messageOf(error) }),
    );
    return () => {
      active = false;
    };
  }, [recipe.id, attempt]);

  const goBack = () => (canGoBack() ? window.history.back() : route('/rezepte', true));

  const setWeek = async () => {
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

  // Off the list without the cooking mode: ask first whether it was cooked.
  const toggleWeek = () =>
    recipe.this_week && cookedSupported && !cookedThisWeek(recipe) ? setAskingCooked(true) : setWeek();

  const ready = content.kind === 'ready' ? content.value : null;
  const base = servingsCount(ready?.servings);
  const factor = base && chosen ? chosen / base : 1;
  const link = sourceLink(recipe);

  return (
    <main class="rezept">
      <div class="rezept-hero">
        <RecipeImage recipe={recipe} size="hero" />
        <button type="button" class="kg-iconbtn kg-iconbtn-schwebend rezept-zurueck" aria-label="Zurück" onClick={goBack}>
          <ZurueckIcon />
        </button>
        <a class="kg-iconbtn kg-iconbtn-schwebend rezept-bearbeiten" href={`${recipePath(recipe)}/bearbeiten`} aria-label="Bearbeiten">
          <StiftIcon size={20} />
        </a>
      </div>

      <div class="rezept-inhalt">
        <header class="rezept-kopf">
          <h1 class="titel-rezept">{recipe.name}</h1>
          <p class="quelle rezept-quelle">{sourceOf(recipe)}</p>
          {(ready && (ready.minutes || ready.servings)) || recipe.last_cooked ? (
            <p class="meta rezept-meta">
              {ready?.minutes ? <span><UhrIcon size={18} />{ready.minutes} Min.</span> : null}
              {ready?.servings ? (
                <span><PortionenIcon size={18} />{/^\d+$/.test(ready.servings) ? `${ready.servings} Portionen` : ready.servings}</span>
              ) : null}
              {recipe.last_cooked ? <span><GekochtIcon size={18} />{cookedLabel(recipe.last_cooked)}</span> : null}
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
          {ready && ready.steps.some((step) => 'text' in step) && (
            <a class="kg-btn kg-btn-gross kg-btn-primaer rezept-kochen" href={`${recipePath(recipe)}/kochen`}>
              <KochenIcon size={20} />Kochmodus starten
            </a>
          )}
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

        <Rating recipe={recipe} />

        {content.kind === 'loading' && <p class="text-klein muted" aria-live="polite">Rezept wird geladen …</p>}
        {content.kind === 'error' && (
          <div class="leer-box" role="alert">
            <p class="text-klein">{content.message}</p>
            <button type="button" class="kg-btn kg-btn-sekundaer" onClick={() => setAttempt((n) => n + 1)}>Nochmal laden</button>
          </div>
        )}
        {ready && <Ingredients recipe={recipe} content={ready} chosen={chosen} onChoose={choose} />}
        {notCreated.length > 0 && (
          <p class="text-klein hinweis" role="status">
            Rezept gespeichert, aber nicht verknüpft: {notCreated.join(', ')}. Dafür braucht KochGuru in Notion
            Schreibrechte auf die Zutaten-Datenbank.
          </p>
        )}
        {ready && (
          <Steps recipe={recipe} content={ready} link={link} factor={factor} onGenerated={(missing) => {
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

      {askingCooked && (
        <AskCookedSheet recipe={recipe} onCancel={() => setAskingCooked(false)}
          onCooked={() => setAskingCooked(false)} onRemoveOnly={() => { setAskingCooked(false); setWeek(); }} />
      )}
    </main>
  );
}

type IngredientsProps = {
  recipe: Recipe;
  content: RecipeContent;
  chosen: number | null;
  onChoose: (servings: number | null) => void;
};

function Ingredients({ content, chosen, onChoose }: IngredientsProps) {
  const count = content.ingredients.filter((i) => !('group' in i)).length;
  const base = servingsCount(content.servings);
  const servings = chosen ?? base;
  const factor = base && servings ? servings / base : 1;
  const set = (n: number) => onChoose(n === base ? null : n);
  return (
    <section class="rezept-abschnitt" aria-labelledby="zutaten-titel">
      <div class="abschnitt-kopf">
        <h2 id="zutaten-titel" class="abschnitt">Zutaten</h2>
        {base && servings && count > 0 ? (
          <div class="portionen" role="group" aria-label="Portionen">
            <button type="button" class="kg-iconbtn portionen-knopf" aria-label="Eine Portion weniger"
              disabled={servings <= 1} onClick={() => set(servings - 1)}>
              <MinusIcon size={18} />
            </button>
            <span class="portionen-zahl" aria-live="polite">
              {servings === 1 ? '1 Portion' : `${servings} Portionen`}
              {servings !== base && (
                <button type="button" class="portionen-zurueck" onClick={() => set(base)}>statt {base}</button>
              )}
            </span>
            <button type="button" class="kg-iconbtn portionen-knopf" aria-label="Eine Portion mehr"
              disabled={servings >= 24} onClick={() => set(servings + 1)}>
              <PlusIcon size={18} />
            </button>
          </div>
        ) : count > 0 ? (
          <p class="meta muted">{count === 1 ? '1 Zutat' : `${count} Zutaten`}</p>
        ) : null}
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
                  {item.amount && <span class="meta muted">{scaleAmount(item.amount, factor)}</span>}
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
type StepsProps = {
  recipe: Recipe;
  content: RecipeContent;
  link: string | null;
  factor: number;
  onGenerated: (notCreated: string[]) => void;
};

function Steps({ recipe, content, link, factor, onGenerated }: StepsProps) {
  let number = 0;
  // Notes or photos on the Notion page are a source too, e.g. when the link is Instagram.
  const hasNotes = content.blocks.length > 0;
  const [again, setAgain] = useState(false);
  const saved = (notCreated: string[]) => {
    setAgain(false);
    onGenerated(notCreated);
  };
  return (
    <section class="rezept-abschnitt" aria-labelledby="zubereitung-titel">
      <h2 id="zubereitung-titel" class="abschnitt">Zubereitung</h2>
      {content.steps.length === 0 ? (
        <Generate recipe={recipe} link={link} canGenerate={Boolean(link) || hasNotes} onSaved={onGenerated} />
      ) : again ? (
        <Generate recipe={recipe} link={link} canGenerate onSaved={saved} again={{ onCancel: () => setAgain(false) }} />
      ) : (
        <>
        <ol class="schritte">
          {content.steps.map((step, index) => {
            if ('group' in step) return <li key={index} class="schritte-gruppe overline">{step.group}</li>;
            number += 1;
            return (
              <li key={index} class="schritt">
                <span class="schritt-nummer" aria-hidden="true">{number}</span>
                <div class="schritt-inhalt">
                  <p class="fliesstext">{step.text}</p>
                  {step.uses && step.uses.length > 0 && <StepAmounts content={content} uses={step.uses} factor={factor} />}
                </div>
              </li>
            );
          })}
        </ol>
        <button type="button" class="neu-generieren" onClick={() => setAgain(true)}>
          <NeuIcon size={16} />Neu generieren
        </button>
        </>
      )}
    </section>
  );
}

// --- Bewertung ---------------------------------------------------------------------------

const NOTE_LINE = /^(\d{2}\.\d{2}\.\d{4}) ([^:]{1,40}): (.*)$/;

/** Both of your stars, your own ones to tap; the notes from the cooking mode, newest first. */
function Rating({ recipe }: { recipe: Recipe }) {
  const { me, people, updateRecipe } = useData();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allNotes, setAllNotes] = useState(false);
  if (people.length === 0 && !recipe.note) return null;

  const run = async (call: () => Promise<Recipe>) => {
    setBusy(true);
    setError(null);
    try {
      updateRecipe(await call());
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };
  const notes = (recipe.note ?? '').split('\n').filter((line) => line.trim()).reverse();
  const shown = allNotes ? notes : notes.slice(0, 3);

  return (
    <section class="bewertung" aria-labelledby="bewertung-titel">
      <h2 id="bewertung-titel" class="titel-block">Eure Bewertung</h2>
      {people.map((person) => (
        <div key={person} class="bewertung-zeile">
          <span class="bewertung-initiale" aria-hidden="true">{person.slice(0, 1)}</span>
          <span class="bewertung-name">{person}</span>
          <Stars value={recipe.ratings?.[person] ?? 0} person={person} disabled={busy}
            onPick={person === me.name ? (stars) => run(() => api.rate(recipe.id, stars)) : undefined} />
        </div>
      ))}
      {shown.length > 0 && (
        <ul class="bewertung-notizen">
          {shown.map((line, i) => {
            const match = NOTE_LINE.exec(line);
            return (
              <li key={i}>
                {match ? (
                  <>
                    <span class="bewertung-notiz-kopf meta muted">{match[2]} · {match[1]}</span>
                    <span>{match[3]}</span>
                  </>
                ) : line}
              </li>
            );
          })}
        </ul>
      )}
      {notes.length > 3 && (
        <button type="button" class="neu-generieren" onClick={() => setAllNotes(!allNotes)}>
          {allNotes ? 'Weniger Notizen' : `Alle ${notes.length} Notizen`}
        </button>
      )}
      {error && <p class="fehler" role="alert">{error}</p>}
    </section>
  );
}

/** Quietly, what the step needs: "600 g Süßkartoffeln · 1 Zwiebel". */
function StepAmounts({ content, uses, factor }: { content: RecipeContent; uses: number[]; factor: number }) {
  const parts = [...new Set(uses.flatMap((i) => {
    const item = content.ingredients[i];
    const amount = item && 'name' in item ? scaleAmount(item.amount, factor) : null;
    return item && 'name' in item ? [`${amount ? `${amount} ` : ''}${shortName(item.name)}`] : [];
  }))];
  return parts.length ? <p class="schritt-mengen meta muted">{parts.join(' · ')}</p> : null;
}

// --- Rezept generieren -----------------------------------------------------------------

type GenerateState =
  | { kind: 'idle' }
  | { kind: 'reading' }
  | {
      kind: 'preview';
      value: GeneratedRecipe;
      include: boolean[];
      cover: boolean;
      /** Ingredient ids to unlink, when generating again. */
      unlink: string[];
      /** The corrected link, when it differs from the recipe's. */
      newLink: string | null;
      saving: boolean;
    }
  | { kind: 'error'; message: string };

function Generate({ recipe, link, canGenerate, onSaved, again }: {
  recipe: Recipe;
  link: string | null;
  canGenerate: boolean;
  onSaved: (notCreated: string[]) => void;
  /** Generate again and replace the earlier version, e.g. after a wrong link. */
  again?: { onCancel: () => void };
}) {
  const { updateRecipe } = useData();
  const [state, setState] = useState<GenerateState>({ kind: 'idle' });
  const [typedLink, setTypedLink] = useState(link ?? '');

  const read = async () => {
    setState({ kind: 'reading' });
    const wanted = typedLink.trim();
    const newLink = again && wanted && wanted !== (link ?? '') ? wanted : null;
    try {
      const value = await api.generate(recipe.id, again ? { link: wanted || null } : undefined);
      // A photo replaces an existing cover only after a corrected link; without a cover it is offered.
      const cover = Boolean(value.image && (!recipe.image || newLink));
      setState({
        kind: 'preview', value, include: value.ingredients.map((i) => i.include), cover,
        unlink: (value.unlink ?? []).map((u) => u.id), newLink, saving: false,
      });
    } catch (error) {
      setState({ kind: 'error', message: messageOf(error) });
    }
  };

  if (again && (state.kind === 'idle' || state.kind === 'error')) {
    return (
      <form class="leer-box" onSubmit={(e) => { e.preventDefault(); read(); }}>
        <h3 class="titel-block">Neu generieren</h3>
        <p class="text-klein muted">
          KochGuru liest das Rezept noch einmal. In der Vorschau siehst du, was sich ändert; die bisherigen
          Zutaten und Schritte werden erst beim Speichern ersetzt.
        </p>
        <label class="neu-link">
          <span class="text-klein">Link zum Rezept</span>
          <span class="kg-search">
            <input type="url" inputMode="url" value={typedLink} placeholder="https://…"
              onInput={(e) => setTypedLink((e.target as HTMLInputElement).value)} />
          </span>
          <span class="meta muted">Ohne Link liest KochGuru die Notizen und Fotos in Notion.</span>
        </label>
        {state.kind === 'error' && <p class="fehler" role="alert">{state.message}</p>}
        <div class="knopf-reihe">
          <button type="submit" class="kg-btn kg-btn-primaer">Generieren</button>
          <button type="button" class="kg-btn kg-btn-sekundaer" onClick={again.onCancel}>Abbrechen</button>
        </div>
      </form>
    );
  }

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
        <p class="text-klein">KochGuru liest das Rezept. Das kann bis zu einer Minute dauern …</p>
      </div>
    );
  }

  const { value, include, cover, unlink, newLink, saving } = state;
  const offerCover = Boolean(value.image && (!recipe.image || again));
  const replacesCover = Boolean(recipe.image);
  const toggle = (index: number) =>
    setState({ ...state, include: include.map((on, i) => (i === index ? !on : on)) });
  const toggleUnlink = (id: string) =>
    setState({ ...state, unlink: unlink.includes(id) ? unlink.filter((u) => u !== id) : [...unlink, id] });
  const replaces = value.replaces;
  const replacesSomething = Boolean(replaces && (replaces.ingredients || replaces.steps || replaces.info));

  const save = async () => {
    setState({ ...state, saving: true });
    try {
      const result = await api.saveGenerated(recipe.id, {
        url: value.url,
        servings: value.servings,
        minutes: value.minutes,
        steps: value.steps,
        cover: offerCover && cover ? value.image : null,
        replace_cover: Boolean(again && replacesCover && cover),
        replace: Boolean(again && replacesSomething),
        unlink: again ? unlink : [],
        new_link: newLink,
        ingredients: value.ingredients.map((item, i) => ({
          line: item.line, zutat: item.zutat, emoji: item.emoji, link: include[i] && item.status !== 'linked',
          aisle: item.aisle ?? null,
        })),
      });
      updateRecipe(result.recipe);
      onSaved(result.not_created);
    } catch (error) {
      setState({ kind: 'error', message: messageOf(error) });
    }
  };
  const discard = () => (again ? again.onCancel() : setState({ kind: 'idle' }));

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
      {again && (
        <p class="text-klein generiert-ersetzt">
          {replacesSomething && replaces
            ? `Ersetzt auf der Notion-Seite ${replacedText(replaces)}. Notizen und Fotos bleiben.`
            : 'Auf der Notion-Seite gibt es keine Abschnitte „Zutaten“ und „Zubereitung“ von KochGuru. Die neue Fassung wird unten angehängt.'}
          {newLink && ' Der Link in Notion wird auf den neuen geändert.'}
        </p>
      )}
      {offerCover && value.image && (
        <label class="generiert-bild">
          <img src={value.image} alt="" referrerpolicy="no-referrer" loading="lazy" />
          <span class="generiert-bild-wahl">
            <input type="checkbox" checked={cover} disabled={saving} onChange={() => setState({ ...state, cover: !cover })} />
            <span class="text-klein">{replacesCover ? 'Titelbild in Notion ersetzen' : 'Als Titelbild in Notion übernehmen'}</span>
          </span>
        </label>
      )}
      <div class="abschnitt-kopf">
        <h3 class="titel-block">Zutaten</h3>
        {value.servings && <p class="meta muted">{value.servings}</p>}
      </div>
      <p class="text-klein muted">Angehakte Zutaten werden mit eurer Zutaten-Datenbank verknüpft und landen damit auf der Einkaufsliste.</p>
      <IngredientChoice items={value.ingredients} include={include} disabled={saving} onToggle={toggle} />
      {again && value.unlink && value.unlink.length > 0 && (
        <>
          <h3 class="titel-block">Bisher verknüpft, im neuen Rezept nicht dabei</h3>
          <p class="text-klein muted">Angehakte Verknüpfungen werden entfernt. Die Zutaten selbst bleiben in eurer Zutaten-Datenbank.</p>
          <ul class="zutaten">
            {value.unlink.map((item) => (
              <li key={item.id} class="zutat generiert-zutat">
                <label>
                  <input type="checkbox" checked={unlink.includes(item.id)} disabled={saving} onChange={() => toggleUnlink(item.id)} />
                  <span class="zutat-emoji" aria-hidden="true">{initialOf(item.name)}</span>
                  <span class="zutat-text">
                    <span class="zutat-name">{item.name}</span>
                    <span class={`meta generiert-status ${unlink.includes(item.id) ? 'generiert-new' : 'generiert-aus'}`}>
                      {unlink.includes(item.id) ? 'Verknüpfung wird entfernt' : 'bleibt verknüpft'}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
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
        <button type="button" class="kg-btn kg-btn-sekundaer" disabled={saving} onClick={discard}>
          Verwerfen
        </button>
      </div>
    </div>
  );
}

function replacedText(replaces: { info: boolean; ingredients: number; steps: number }): string {
  const parts: string[] = [];
  if (replaces.ingredients) parts.push(`die Zutaten (${replaces.ingredients} ${replaces.ingredients === 1 ? 'Zeile' : 'Zeilen'})`);
  if (replaces.steps) parts.push(`die Zubereitung (${replaces.steps} ${replaces.steps === 1 ? 'Schritt' : 'Schritte'})`);
  if (replaces.info) parts.push('die Infozeile mit der Quelle');
  return parts.length > 1 ? `${parts.slice(0, -1).join(', ')} und ${parts[parts.length - 1]}` : parts[0];
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
