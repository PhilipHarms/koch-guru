import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type ChoiceField, type Recipe, type RecipeChanges, type RecipeFields } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf, recipePath, sameId } from '../lib/recipe';
import { preparePhoto } from '../lib/photos';
import { RecipeImage } from '../components/RecipeImage';
import { KameraIcon, KreuzIcon, PlusIcon } from '../components/icons';
import { PlaceholderPage } from './Placeholder';

export function EditRoute({ id }: { id: string }) {
  const { recipes } = useData();
  const recipe = recipes.find((r) => sameId(r.id, id));
  if (!recipe) return <PlaceholderPage title="Nicht gefunden" text="Dieses Rezept gibt es nicht mehr in Notion." />;
  return <EditPage recipe={recipe} />;
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i]);

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

  useEffect(() => window.scrollTo(0, 0), []);
  useEffect(() => {
    api.recipeFields().then(setFields, () => setFields({ tags: null, origin: null, link: true }));
  }, []);
  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo.url); }, [photo]);

  const leave = () => (canGoBack() ? window.history.back() : route(recipePath(recipe), true));

  const changes: RecipeChanges = {};
  if (name.trim() !== recipe.name) changes.name = name.trim();
  if (emoji.trim() !== (recipe.emoji ?? '')) changes.emoji = emoji.trim() || null;
  if (!same(tags, recipe.tags)) changes.tags = tags;
  if (!same(origin, recipe.origin)) changes.origin = origin;
  if (link.trim() !== (recipe.source_url ?? '')) changes.link = link.trim() || null;
  const coverChanged = Boolean(photo) || (dropCover && Boolean(recipe.image));
  const changed = Object.keys(changes).length > 0 || coverChanged;

  const save = async () => {
    if (!name.trim()) {
      setError('Das Rezept braucht einen Namen.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      let updated = recipe;
      if (Object.keys(changes).length) updated = await api.updateRecipe(recipe.id, changes);
      if (photo) updated = await api.setCover(recipe.id, await preparePhoto(photo.file, 1600));
      else if (dropCover && recipe.image) updated = await api.removeCover(recipe.id);
      updateRecipe(updated);
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
