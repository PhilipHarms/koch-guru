import { useEffect, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type ImportPreview, type Recipe } from '../lib/api';
import { useData } from '../lib/data';
import { canGoBack } from '../lib/nav';
import { messageOf, recipePath } from '../lib/recipe';
import { preparePhoto } from '../lib/photos';
import { IngredientChoice } from '../components/IngredientChoice';
import { BildIcon, HakenIcon, KameraIcon, KreuzIcon, LinkIcon } from '../components/icons';

const MAX_PHOTOS = 4;

type Source = 'link' | 'foto';
type Picked = { key: number; file: File; url: string };

type State =
  | { kind: 'input'; error?: string }
  | { kind: 'reading' }
  | { kind: 'existing'; recipe: Recipe }
  | {
      kind: 'preview';
      value: ImportPreview;
      include: boolean[];
      tags: string[];
      cover: boolean;
      saving: boolean;
      error?: string;
    }
  | { kind: 'saved'; recipe: Recipe; notCreated: string[] };

export function ImportRoute() {
  return <ImportPage />;
}

/** "Rezept hinzufügen": read a recipe from a link or photos, check the preview, save it to Notion. */
export function ImportPage() {
  const { addRecipe } = useData();
  const { route, query } = useLocation();
  const [source, setSource] = useState<Source>('link');
  const [link, setLink] = useState(() => query.url ?? query.text ?? '');
  const [photos, setPhotos] = useState<Picked[]>([]);
  const [caption, setCaption] = useState('');
  const [state, setState] = useState<State>({ kind: 'input' });
  const camera = useRef<HTMLInputElement>(null);
  const library = useRef<HTMLInputElement>(null);
  const counter = useRef(0);

  useEffect(() => window.scrollTo(0, 0), [state.kind]);
  useEffect(() => () => photos.forEach((p) => URL.revokeObjectURL(p.url)), []);

  const close = () => (canGoBack() ? window.history.back() : route('/rezepte', true));

  const pick = (files: FileList | null) => {
    const added = [...(files ?? [])]
      .filter((file) => file.type.startsWith('image/') || /\.(heic|heif)$/i.test(file.name))
      .map((file) => ({ key: ++counter.current, file, url: URL.createObjectURL(file) }));
    setPhotos((current) => {
      const next = [...current, ...added];
      next.slice(MAX_PHOTOS).forEach((p) => URL.revokeObjectURL(p.url));
      return next.slice(0, MAX_PHOTOS);
    });
  };
  const removePhoto = (key: number) =>
    setPhotos((current) => {
      current.filter((p) => p.key === key).forEach((p) => URL.revokeObjectURL(p.url));
      return current.filter((p) => p.key !== key);
    });

  const ready = source === 'link' ? link.trim().length > 0 : photos.length > 0;

  const read = async () => {
    if (!ready) return;
    setState({ kind: 'reading' });
    try {
      const result = source === 'link'
        ? await api.importRecipe({ url: link.trim() })
        : await api.importRecipe({
            photos: await Promise.all(photos.map((p) => preparePhoto(p.file))),
            caption: caption.trim(),
          });
      if ('existing' in result) {
        setState({ kind: 'existing', recipe: result.existing });
        return;
      }
      setState({
        kind: 'preview', value: result, include: result.ingredients.map((i) => i.include), tags: result.tags,
        cover: Boolean(result.image), saving: false,
      });
    } catch (error) {
      setState({ kind: 'input', error: messageOf(error) });
    }
  };

  const startOver = () => {
    photos.forEach((p) => URL.revokeObjectURL(p.url));
    setPhotos([]);
    setLink('');
    setCaption('');
    setState({ kind: 'input' });
  };

  return (
    <main class="page import">
      <header class="page-header import-kopf">
        <h1 class="titel-seite">Rezept hinzufügen</h1>
        <button type="button" class="kg-iconbtn" aria-label="Schließen" onClick={close}>
          <KreuzIcon size={20} />
        </button>
      </header>

      {state.kind === 'input' && (
        <form class="page-pad import-eingabe" onSubmit={(e) => { e.preventDefault(); read(); }}>
          <div class="kg-seg import-quelle" role="group" aria-label="Quelle">
            <button type="button" aria-pressed={source === 'link'} onClick={() => setSource('link')}>
              <LinkIcon size={18} />Link
            </button>
            <button type="button" aria-pressed={source === 'foto'} onClick={() => setSource('foto')}>
              <KameraIcon size={18} />Foto
            </button>
          </div>

          {source === 'link' ? (
            <div class="import-feld">
              <label class="titel-block" for="rezept-link">Link zum Rezept</label>
              <span class="kg-search">
                <input id="rezept-link" type="url" inputMode="url" placeholder="https://…" value={link} autocomplete="off"
                  onInput={(e) => setLink((e.target as HTMLInputElement).value)} />
              </span>
              <p class="text-klein muted">Klappt mit den meisten Rezeptseiten. Instagram und TikTok kann KochGuru leider nicht lesen.</p>
            </div>
          ) : (
            <div class="import-feld">
              <div class="import-fotoknoepfe">
                <button type="button" class="import-fotoknopf" disabled={photos.length >= MAX_PHOTOS}
                  onClick={() => camera.current?.click()}>
                  <KameraIcon size={30} />Foto aufnehmen
                </button>
                <button type="button" class="import-fotoknopf" disabled={photos.length >= MAX_PHOTOS}
                  onClick={() => library.current?.click()}>
                  <BildIcon size={30} />Aus Fotos wählen
                </button>
              </div>
              <input ref={camera} class="kg-sr" type="file" accept="image/*" capture="environment" tabIndex={-1}
                onChange={(e) => { pick((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = ''; }} />
              <input ref={library} class="kg-sr" type="file" accept="image/*" multiple tabIndex={-1}
                onChange={(e) => { pick((e.target as HTMLInputElement).files); (e.target as HTMLInputElement).value = ''; }} />
              {photos.length > 0 && (
                <ul class="import-fotos" aria-label="Ausgewählte Fotos">
                  {photos.map((photo, index) => (
                    <li key={photo.key}>
                      <img src={photo.url} alt={`Foto ${index + 1}`} />
                      <button type="button" class="kg-iconbtn import-foto-weg" aria-label={`Foto ${index + 1} entfernen`}
                        onClick={() => removePhoto(photo.key)}>
                        <KreuzIcon size={16} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <label class="titel-block" for="bildunterschrift">Woher stammt das Rezept? (optional)</label>
              <span class="kg-search">
                <input id="bildunterschrift" type="text" placeholder="z. B. Green Feast, Seite 112" value={caption}
                  onInput={(e) => setCaption((e.target as HTMLInputElement).value)} />
              </span>
              <p class="text-klein muted">Geht das Rezept über zwei Seiten, wähl einfach beide Fotos aus.</p>
            </div>
          )}

          {state.error && <p class="fehler" role="alert">{state.error}</p>}
          <button type="submit" class="kg-btn kg-btn-gross kg-btn-primaer" disabled={!ready}>Einlesen</button>
        </form>
      )}

      {state.kind === 'reading' && (
        <div class="page-pad">
          <div class="leer-box" aria-live="polite">
            <p class="text-klein">KochGuru liest das Rezept. Das kann bis zu einer Minute dauern …</p>
          </div>
        </div>
      )}

      {state.kind === 'existing' && (
        <div class="page-pad import-fertig" role="status">
          <h2 class="titel-block">Das Rezept ist schon in eurer Sammlung</h2>
          <p class="text-klein muted">„{state.recipe.name}“ hat denselben Link.</p>
          <a class="kg-btn kg-btn-gross kg-btn-primaer" href={recipePath(state.recipe)}>Rezept ansehen</a>
          <button type="button" class="kg-btn import-nochmal" onClick={startOver}>Anderes Rezept hinzufügen</button>
        </div>
      )}

      {state.kind === 'preview' && (
        <Preview state={state} onChange={setState} onDiscard={() => setState({ kind: 'input' })} onSaved={(recipe, notCreated) => {
          addRecipe(recipe);
          setState({ kind: 'saved', recipe, notCreated });
        }} />
      )}

      {state.kind === 'saved' && (
        <div class="page-pad import-fertig" role="status">
          <span class="import-haken" aria-hidden="true"><HakenIcon size={34} /></span>
          <h2 class="titel-rezept">{state.recipe.name} ist gespeichert</h2>
          <p class="text-klein muted">Es steht jetzt in eurer Notion-Sammlung.</p>
          {state.notCreated.length > 0 && (
            <p class="text-klein hinweis">
              Nicht verknüpft: {state.notCreated.join(', ')}. Dafür braucht KochGuru in Notion Schreibrechte auf die
              Zutaten-Datenbank.
            </p>
          )}
          <a class="kg-btn kg-btn-gross kg-btn-primaer" href={recipePath(state.recipe)}>Rezept ansehen</a>
          <button type="button" class="kg-btn import-nochmal" onClick={startOver}>Noch ein Rezept hinzufügen</button>
        </div>
      )}
    </main>
  );
}

type PreviewState = Extract<State, { kind: 'preview' }>;

function infoLine(value: ImportPreview): string {
  const parts = [value.site ?? (value.origin.length ? `Foto · ${value.origin.join(', ')}` : 'Foto')];
  if (value.minutes) parts.push(`${value.minutes} Min.`);
  if (value.servings) parts.push(value.servings);
  return parts.join(' · ');
}

function Preview({ state, onChange, onDiscard, onSaved }: {
  state: PreviewState;
  onChange: (state: PreviewState) => void;
  onDiscard: () => void;
  onSaved: (recipe: Recipe, notCreated: string[]) => void;
}) {
  const { value, include, tags, cover, saving } = state;
  const toggle = (index: number) => onChange({ ...state, include: include.map((on, i) => (i === index ? !on : on)) });
  const toggleTag = (tag: string) =>
    onChange({ ...state, tags: tags.includes(tag) ? tags.filter((t) => t !== tag) : [...tags, tag] });

  const save = async () => {
    onChange({ ...state, saving: true, error: undefined });
    try {
      const result = await api.saveImport(value.draft_id, {
        name: value.name,
        tags: value.tag_options.filter((t) => tags.includes(t)),
        servings: value.servings,
        steps: value.steps,
        cover,
        ingredients: value.ingredients.map((item, i) => ({
          line: item.line, zutat: item.zutat, emoji: item.emoji, link: include[i], aisle: item.aisle ?? null,
        })),
      });
      onSaved(result.recipe, result.not_created);
    } catch (error) {
      onChange({ ...state, saving: false, error: messageOf(error) });
    }
  };

  return (
    <div class="page-pad generiert import-vorschau" aria-live="polite">
      <div class="import-titel">
        <span class="import-emoji" aria-hidden="true">{value.icon ?? '🍽️'}</span>
        <span class="import-titel-text">
          <span class="titel-rezept">{value.name}</span>
          <span class="meta muted">{infoLine(value)}</span>
        </span>
      </div>

      {value.similar && (
        <p class="text-klein generiert-ersetzt">
          In eurer Sammlung gibt es schon <a href={recipePath(value.similar)}>„{value.similar.name}“</a>. Speichern legt
          ein zweites Rezept an.
        </p>
      )}

      {value.image && (
        <label class="generiert-bild">
          <img src={value.image} alt="" referrerpolicy="no-referrer" loading="lazy" />
          <span class="generiert-bild-wahl">
            <input type="checkbox" checked={cover} disabled={saving} onChange={() => onChange({ ...state, cover: !cover })} />
            <span class="text-klein">Als Titelbild übernehmen</span>
          </span>
        </label>
      )}

      {value.tag_options.length > 0 && (
        <div class="import-tags">
          <h3 class="titel-block">Tags</h3>
          <div class="import-tag-liste" role="group" aria-label="Tags">
            {value.tag_options.map((tag) => (
              <button type="button" key={tag} class="kg-chip import-tag" aria-pressed={tags.includes(tag)} disabled={saving}
                onClick={() => toggleTag(tag)}>
                {tag}
              </button>
            ))}
          </div>
        </div>
      )}

      <div class="abschnitt-kopf">
        <h3 class="titel-block">Zutaten</h3>
        {value.servings && <p class="meta muted">{value.servings}</p>}
      </div>
      <p class="text-klein muted">Angehakte Zutaten werden mit eurer Zutaten-Datenbank verknüpft und landen damit auf der Einkaufsliste.</p>
      <IngredientChoice items={value.ingredients} include={include} disabled={saving} onToggle={toggle} />

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
        <p class="text-klein muted">In der Quelle stehen keine Schritte.</p>
      )}

      {value.from_photo && (
        <p class="text-klein muted">Vom Foto gelesen, bitte kurz prüfen. Das Foto hängt KochGuru an das Rezept.</p>
      )}
      {state.error && <p class="fehler" role="alert">{state.error}</p>}
      <div class="knopf-reihe import-knoepfe">
        <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer" disabled={saving} onClick={onDiscard}>Verwerfen</button>
        <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer" disabled={saving} onClick={save}>
          {saving ? 'Speichert …' : 'Speichern'}
        </button>
      </div>
    </div>
  );
}
