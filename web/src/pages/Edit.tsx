import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type ChoiceField, type EditContent, type IngredientCheck, type Recipe, type RecipeChanges, type RecipeFields } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf, recipePath, sameId } from '../lib/recipe';
import { preparePhoto } from '../lib/photos';
import { RecipeImage } from '../components/RecipeImage';
import { IngredientChoice } from '../components/IngredientChoice';
import { LinesEditor, toLines, type Line } from '../components/LinesEditor';
import { KameraIcon, KreuzIcon, PlusIcon } from '../components/icons';
import { PlaceholderPage } from './Placeholder';

export function EditRoute({ id }: { id: string }) {
  const { recipes } = useData();
  const recipe = recipes.find((r) => sameId(r.id, id));
  if (!recipe) return <PlaceholderPage title="Nicht gefunden" text="Dieses Rezept gibt es nicht mehr in Notion." />;
  return <EditPage recipe={recipe} />;
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i]);
const clean = (lines: Line[] | string[]) =>
  lines.map((l) => (typeof l === 'string' ? l : l.text).replace(/\s+/g, ' ').trim()).filter(Boolean);

type Review = IngredientCheck & { include: boolean[]; unlinkChosen: string[] };

/** Change a recipe's name, emoji, tags, cookbook, link and cover photo. Saved to Notion on "Speichern". */
export function EditPage({ recipe }: { recipe: Recipe }) {
  const { updateRecipe } = useData();
  const { route } = useLocation();
  const [fields, setFields] = useState<RecipeFields | null>(null);
  const [name, setName] = useState(recipe.name);
  const [emoji, setEmoji] = useState(recipe.emoji ?? '');
  const [tags, setTags] = useState<string[]>(recipe.tags);
  const [origin, setOrigin] = useState<string[]>(recipe.origin);
  const [link, setLink] = useState(recipe.source_url ?? '');
  const [photo, setPhoto] = useState<{ file: File; url: string } | null>(null);
  const [dropCover, setDropCover] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  // Content: ingredients, steps, time and servings.
  const [original, setOriginal] = useState<EditContent | 'loading' | 'error'>('loading');
  const [minutes, setMinutes] = useState('');
  const [servings, setServings] = useState('');
  const [ingredients, setIngredients] = useState<Line[]>([]);
  const [steps, setSteps] = useState<Line[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [notLinked, setNotLinked] = useState<string[] | null>(null);

  useEffect(() => window.scrollTo(0, 0), [review === null]);
  useEffect(() => {
    api.recipeFields().then(setFields, () => setFields({ tags: null, origin: null, link: true }));
    api.editContent(recipe.id).then((content) => {
      setOriginal(content);
      setMinutes(content.minutes ? String(content.minutes) : '');
      setServings(content.servings ?? '');
      setIngredients(toLines(content.ingredients));
      setSteps(toLines(content.steps));
    }, () => setOriginal('error'));
  }, [recipe.id]);
  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo.url); }, [photo]);

  const leave = () => (canGoBack() ? window.history.back() : route(recipePath(recipe), true));

  const changes: RecipeChanges = {};
  if (name.trim() !== recipe.name) changes.name = name.trim();
  if (emoji.trim() !== (recipe.emoji ?? '')) changes.emoji = emoji.trim() || null;
  if (!same(tags, recipe.tags)) changes.tags = tags;
  if (!same(origin, recipe.origin)) changes.origin = origin;
  if (link.trim() !== (recipe.source_url ?? '')) changes.link = link.trim() || null;
  const coverChanged = Boolean(photo) || (dropCover && Boolean(recipe.image));
  const content = typeof original === 'object' && original.editable ? original : null;
  const minutesValue = Number.parseInt(minutes, 10) > 0 ? Number.parseInt(minutes, 10) : null;
  const ingredientsChanged = Boolean(content) && !same(clean(ingredients), clean(content!.ingredients));
  const contentChanged = Boolean(content) && (
    ingredientsChanged
    || !same(clean(steps), clean(content!.steps))
    || minutesValue !== content!.minutes
    || servings.trim() !== (content!.servings ?? '')
  );
  const changed = Object.keys(changes).length > 0 || coverChanged || contentChanged;

  /** First step of saving: new ingredient lines and lost links get a look before anything is written. */
  const save = async () => {
    if (!name.trim()) {
      setError('Das Rezept braucht einen Namen.');
      return;
    }
    setError(null);
    if (ingredientsChanged) {
      setSaving(true);
      try {
        const check = await api.checkIngredients(recipe.id, clean(ingredients));
        if (check.lines.length || check.unlink.length) {
          setReview({ ...check, include: check.lines.map((l) => l.include), unlinkChosen: check.unlink.map((u) => u.id) });
          setSaving(false);
          return;
        }
      } catch (e) {
        setError(messageOf(e));
        setSaving(false);
        return;
      }
    }
    await write(null);
  };

  const write = async (decided: Review | null) => {
    setSaving(true);
    setError(null);
    try {
      let updated = recipe;
      let missing: string[] = [];
      if (Object.keys(changes).length) updated = await api.updateRecipe(recipe.id, changes);
      if (contentChanged) {
        const result = await api.saveContent(recipe.id, {
          minutes: minutesValue,
          servings: servings.trim() || null,
          ingredients: clean(ingredients),
          steps: clean(steps),
          link: decided
            ? decided.lines.filter((_, i) => decided.include[i]).map((l) => ({ zutat: l.zutat, emoji: l.emoji, aisle: l.aisle ?? null }))
            : [],
          unlink: decided ? decided.unlinkChosen : [],
        });
        updated = result.recipe;
        missing = result.not_created;
      }
      if (photo) updated = await api.setCover(recipe.id, await preparePhoto(photo.file, 1600));
      else if (dropCover && recipe.image) updated = await api.removeCover(recipe.id);
      updateRecipe(updated);
      if (missing.length) {
        setNotLinked(missing);
        setReview(null);
        setSaving(false);
        return;
      }
      leave();
    } catch (e) {
      setError(messageOf(e));
      setSaving(false);
    }
  };

  const choosePhoto = (file: File | undefined) => {
    if (!file) return;
    setPhoto({ file, url: URL.createObjectURL(file) });
    setDropCover(false);
  };

  const showsImage = photo ? true : Boolean(recipe.image) && !dropCover;

  if (notLinked) {
    return (
      <main class="page bearbeiten">
        <div class="page-pad import-fertig" role="status">
          <h2 class="titel-block">Gespeichert</h2>
          <p class="text-klein hinweis">
            Nicht verknüpft: {notLinked.join(', ')}. Dafür braucht KochGuru in Notion Schreibrechte auf die Zutaten-Datenbank.
          </p>
          <a class="kg-btn kg-btn-gross kg-btn-primaer" href={recipePath(recipe)}>Zum Rezept</a>
        </div>
      </main>
    );
  }

  if (review) {
    const toggle = (index: number) => setReview({ ...review, include: review.include.map((on, i) => (i === index ? !on : on)) });
    const toggleUnlink = (id: string) => setReview({
      ...review,
      unlinkChosen: review.unlinkChosen.includes(id) ? review.unlinkChosen.filter((u) => u !== id) : [...review.unlinkChosen, id],
    });
    return (
      <main class="page bearbeiten">
        <header class="page-header import-kopf">
          <h1 class="titel-seite">Zutaten verknüpfen</h1>
        </header>
        <div class="page-pad generiert import-vorschau">
          {review.lines.length > 0 && (
            <>
              <h3 class="titel-block">Neue Zutaten</h3>
              <p class="text-klein muted">Angehakte Zutaten werden mit eurer Zutaten-Datenbank verknüpft und landen damit auf der Einkaufsliste.</p>
              <IngredientChoice items={review.lines} include={review.include} disabled={saving} onToggle={toggle} />
            </>
          )}
          {review.unlink.length > 0 && (
            <>
              <h3 class="titel-block">Nicht mehr im Rezept</h3>
              <p class="text-klein muted">Angehakte Verknüpfungen werden entfernt. Die Zutaten selbst bleiben in eurer Zutaten-Datenbank.</p>
              <ul class="zutaten">
                {review.unlink.map((item) => (
                  <li key={item.id} class="zutat generiert-zutat">
                    <label>
                      <input type="checkbox" checked={review.unlinkChosen.includes(item.id)} disabled={saving}
                        onChange={() => toggleUnlink(item.id)} />
                      <span class="zutat-text">
                        <span class="zutat-name">{item.name}</span>
                        <span class={`meta generiert-status ${review.unlinkChosen.includes(item.id) ? 'generiert-new' : 'generiert-aus'}`}>
                          {review.unlinkChosen.includes(item.id) ? 'Verknüpfung wird entfernt' : 'bleibt verknüpft'}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </>
          )}
          {error && <p class="fehler" role="alert">{error}</p>}
          <div class="knopf-reihe import-knoepfe">
            <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer" disabled={saving} onClick={() => setReview(null)}>Zurück</button>
            <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer" disabled={saving} onClick={() => write(review)}>
              {saving ? 'Speichert …' : 'Speichern'}
            </button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main class="page bearbeiten">
      <header class="page-header import-kopf">
        <h1 class="titel-seite">Bearbeiten</h1>
        <button type="button" class="kg-iconbtn" aria-label="Schließen" onClick={leave}>
          <KreuzIcon size={20} />
        </button>
      </header>

      <form class="page-pad bearbeiten-formular" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <section class="bearbeiten-feld" aria-labelledby="titelbild">
          <h2 class="titel-block" id="titelbild">Titelbild</h2>
          <div class="bearbeiten-bild">
            {photo ? (
              <img src={photo.url} alt="Neues Titelbild" />
            ) : (
              <RecipeImage recipe={{ ...recipe, image: showsImage ? recipe.image : null, emoji: emoji.trim() || null }} size="hero" />
            )}
          </div>
          <div class="knopf-reihe">
            <button type="button" class="kg-btn kg-btn-sekundaer" disabled={saving} onClick={() => picker.current?.click()}>
              <KameraIcon size={18} />{showsImage ? 'Anderes Foto' : 'Foto wählen'}
            </button>
            {showsImage && (
              <button type="button" class="kg-btn import-nochmal" disabled={saving}
                onClick={() => (photo ? setPhoto(null) : setDropCover(true))}>
                {photo ? 'Doch nicht' : 'Entfernen'}
              </button>
            )}
            {!photo && dropCover && (
              <button type="button" class="kg-btn import-nochmal" disabled={saving} onClick={() => setDropCover(false)}>
                Behalten
              </button>
            )}
          </div>
          <input ref={picker} class="kg-sr" type="file" accept="image/*" tabIndex={-1}
            onChange={(e) => { const el = e.target as HTMLInputElement; choosePhoto(el.files?.[0]); el.value = ''; }} />
        </section>

        <div class="bearbeiten-feld">
          <label class="titel-block" for="name">Name</label>
          <span class="kg-search">
            <input id="name" type="text" value={name} maxLength={200} disabled={saving}
              onInput={(e) => setName((e.target as HTMLInputElement).value)} />
          </span>
        </div>

        <div class="bearbeiten-feld">
          <label class="titel-block" for="emoji">Emoji</label>
          <span class="kg-search bearbeiten-emoji">
            <input id="emoji" type="text" value={emoji} maxLength={16} disabled={saving} autocomplete="off"
              onInput={(e) => setEmoji((e.target as HTMLInputElement).value)} />
          </span>
          <p class="text-klein muted">Erscheint, solange das Rezept kein Titelbild hat.</p>
        </div>

        {fields?.tags && (
          <Choice title="Tags" field={fields.tags} selected={tags} onChange={setTags} disabled={saving} addLabel="Neuer Tag" />
        )}
        {fields?.origin && (
          <Choice title="Kochbuch" field={fields.origin} selected={origin} onChange={setOrigin} disabled={saving}
            addLabel="Anderes Kochbuch" />
        )}

        {(fields?.link ?? true) && (
          <div class="bearbeiten-feld">
            <label class="titel-block" for="link">Link zum Originalrezept</label>
            <span class="kg-search">
              <input id="link" type="url" inputMode="url" placeholder="https://…" value={link} disabled={saving}
                onInput={(e) => setLink((e.target as HTMLInputElement).value)} />
            </span>
          </div>
        )}

        {original === 'loading' && <p class="text-klein muted" aria-live="polite">Zutaten und Schritte werden geladen …</p>}
        {original === 'error' && <p class="text-klein muted">Zutaten und Schritte konnten nicht geladen werden.</p>}
        {typeof original === 'object' && !original.editable && (
          <div class="leer-box">
            <p class="text-klein">
              Zutaten und Schritte stehen auf dieser Seite nicht unter den Überschriften „Zutaten“ und „Zubereitung“.
              Deshalb lassen sie sich nur in Notion ändern.
            </p>
            <a class="rezept-link" href={recipe.notion_url} target="_blank" rel="noopener noreferrer">In Notion öffnen</a>
          </div>
        )}
        {content && (
          <>
            <div class="bearbeiten-feld">
              <h2 class="titel-block">Zeit und Portionen</h2>
              <div class="bearbeiten-zwei">
                <label class="bearbeiten-klein">
                  <span class="text-klein muted">Minuten</span>
                  <span class="kg-search">
                    <input type="number" inputMode="numeric" min={0} max={10000} value={minutes} disabled={saving}
                      onInput={(e) => setMinutes((e.target as HTMLInputElement).value)} />
                  </span>
                </label>
                <label class="bearbeiten-klein">
                  <span class="text-klein muted">Portionen</span>
                  <span class="kg-search">
                    <input type="text" value={servings} maxLength={100} placeholder="z. B. 4" disabled={saving}
                      onInput={(e) => setServings((e.target as HTMLInputElement).value)} />
                  </span>
                </label>
              </div>
            </div>
            <div class="bearbeiten-feld">
              <h2 class="titel-block">Zutaten</h2>
              <p class="text-klein muted">Eine Zutat pro Zeile, mit Menge. Zwischenüberschriften mit Doppelpunkt, z. B. „Für die Soße:“.</p>
              <LinesEditor lines={ingredients} onChange={setIngredients} numbered={false} label="Zutat"
                addLabel="Zutat hinzufügen" placeholder="z. B. 200 g rote Linsen" disabled={saving} />
            </div>
            <div class="bearbeiten-feld">
              <h2 class="titel-block">Zubereitung</h2>
              <LinesEditor lines={steps} onChange={setSteps} numbered label="Schritt"
                addLabel="Schritt hinzufügen" placeholder="Was ist zu tun?" disabled={saving} />
            </div>
          </>
        )}

        {error && <p class="fehler" role="alert">{error}</p>}
        <div class="knopf-reihe import-knoepfe">
          <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer" disabled={saving} onClick={leave}>Abbrechen</button>
          <button type="submit" class="kg-btn kg-btn-gross kg-btn-primaer" disabled={saving || !changed}>
            {saving ? 'Speichert …' : 'Speichern'}
          </button>
        </div>
      </form>
    </main>
  );
}

/** Chips for the options in Notion, plus a field to add a new one. */
function Choice({ title, field, selected, onChange, disabled, addLabel }: {
  title: string;
  field: NonNullable<ChoiceField>;
  selected: string[];
  onChange: (values: string[]) => void;
  disabled: boolean;
  addLabel: string;
}) {
  const [typed, setTyped] = useState('');
  const options = [...field.options, ...selected.filter((s) => !field.options.includes(s))];
  const toggle = (value: string) => {
    if (selected.includes(value)) onChange(selected.filter((s) => s !== value));
    else onChange(field.multiple ? [...selected, value] : [value]);
  };
  const add = () => {
    const value = typed.replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
    if (!value) return;
    const known = options.find((o) => o.toLocaleLowerCase('de') === value.toLocaleLowerCase('de'));
    const chosen = known ?? value;
    if (!selected.includes(chosen)) onChange(field.multiple ? [...selected, chosen] : [chosen]);
    setTyped('');
  };

  return (
    <div class="bearbeiten-feld">
      <h2 class="titel-block">{title}</h2>
      {options.length > 0 && (
        <div class="import-tag-liste" role="group" aria-label={title}>
          {options.map((option) => (
            <button type="button" key={option} class="kg-chip import-tag" aria-pressed={selected.includes(option)}
              disabled={disabled} onClick={() => toggle(option)}>
              {option}
            </button>
          ))}
        </div>
      )}
      <div class="bearbeiten-neu">
        <span class="kg-search">
          <input type="text" placeholder={addLabel} aria-label={addLabel} value={typed} maxLength={100} disabled={disabled}
            onInput={(e) => setTyped((e.target as HTMLInputElement).value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} />
        </span>
        <button type="button" class="kg-iconbtn" aria-label={`${addLabel} hinzufügen`} disabled={disabled || !typed.trim()}
          onClick={add}>
          <PlusIcon size={20} />
        </button>
      </div>
    </div>
  );
}
