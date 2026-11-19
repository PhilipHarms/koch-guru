import { Fragment } from 'preact';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { api, type Ingredient, type Recipe, type RecipeContent } from '../lib/api';
import { useData } from '../lib/data';
import { clock, findDuration } from '../lib/duration';
import { canGoBack } from '../lib/nav';
import { messageOf, recipePath, sameId } from '../lib/recipe';
import { HakenIcon, KreuzIcon, ListeIcon, UhrIcon, WeiterIcon } from '../components/icons';
import { PlaceholderPage } from './Placeholder';

type CookStep = { text: string; group: string | null; uses: number[] };
type Timer = { endsAt: number; seconds: number; rang: boolean };
/** Where you were in a recipe, so closing the cooking mode by mistake loses nothing. */
type Session = { index: number; timers: Record<number, Timer> };

const sessions = new Map<string, Session>();

function cookSteps(content: RecipeContent): CookStep[] {
  const steps: CookStep[] = [];
  let group: string | null = null;
  for (const step of content.steps) {
    if ('group' in step) group = step.group;
    else steps.push({ text: step.text, group, uses: step.uses ?? [] });
  }
  return steps;
}

export function CookRoute({ id }: { id: string }) {
  const { recipes } = useData();
  const recipe = recipes.find((r) => sameId(r.id, id));
  if (!recipe) return <PlaceholderPage title="Nicht gefunden" text="Dieses Rezept gibt es nicht mehr in Notion." />;
  return <CookLoader recipe={recipe} />;
}

function CookLoader({ recipe }: { recipe: Recipe }) {
  const [content, setContent] = useState<RecipeContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    api.content(recipe.id).then(
      (value) => active && setContent(value),
      (err) => active && setError(messageOf(err)),
    );
    return () => {
      active = false;
    };
  }, [recipe.id]);

  if (error || (content && cookSteps(content).length === 0)) {
    return (
      <div class="kochmodus">
        <div class="kochmodus-leer">
          <p class="text-klein">{error ?? 'Für dieses Rezept stehen in Notion noch keine Schritte.'}</p>
          <a class="kg-btn kg-btn-sekundaer" href={recipePath(recipe)}>Zum Rezept</a>
        </div>
      </div>
    );
  }
  if (!content) {
    return (
      <div class="kochmodus">
        <p class="kochmodus-leer text-klein muted" aria-live="polite">Kochmodus wird vorbereitet …</p>
      </div>
    );
  }
  return <CookMode recipe={recipe} content={content} />;
}

// --- Sound and screen ---------------------------------------------------------------------

let audio: AudioContext | null = null;

/** Browsers only allow sound after a tap, so the context is opened when a timer starts. */
function unlockAudio(): void {
  try {
    const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    audio ??= new Context();
    void audio.resume();
  } catch {
    audio = null;
  }
}

function ring(): void {
  navigator.vibrate?.([300, 150, 300, 150, 300]);
  if (!audio) return;
  const start = audio.currentTime;
  for (let i = 0; i < 3; i += 1) {
    const tone = audio.createOscillator();
    const gain = audio.createGain();
    tone.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, start + i * 0.45);
    gain.gain.exponentialRampToValueAtTime(0.4, start + i * 0.45 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + i * 0.45 + 0.3);
    tone.connect(gain).connect(audio.destination);
    tone.start(start + i * 0.45);
    tone.stop(start + i * 0.45 + 0.32);
  }
}

type WakeLock = { release: () => Promise<void>; addEventListener: (type: 'release', f: () => void) => void };

/** Keeps the screen on while cooking, where the browser allows it. */
function useScreenAwake(): boolean {
  const [awake, setAwake] = useState(false);
  useEffect(() => {
    let lock: WakeLock | null = null;
    let active = true;
    const request = async () => {
      try {
        const api = (navigator as unknown as { wakeLock?: { request: (t: 'screen') => Promise<WakeLock> } }).wakeLock;
        if (!api) return;
        lock = await api.request('screen');
        if (!active) {
          void lock.release();
          return;
        }
        setAwake(true);
        lock.addEventListener('release', () => setAwake(false));
      } catch {
        setAwake(false);
      }
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') void request();
    };
    void request();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      active = false;
      document.removeEventListener('visibilitychange', onVisible);
      void lock?.release().catch(() => undefined);
    };
  }, []);
  return awake;
}

// --- Cooking mode ---------------------------------------------------------------------------

function CookMode({ recipe, content }: { recipe: Recipe; content: RecipeContent }) {
  const { route } = useLocation();
  const steps = useMemo(() => cookSteps(content), [content]);
  const saved = sessions.get(recipe.id);
  const [index, setIndex] = useState(Math.min(saved?.index ?? 0, steps.length - 1));
  const [timers, setTimers] = useState<Record<number, Timer>>(saved?.timers ?? {});
  const [now, setNow] = useState(Date.now());
  const [showAll, setShowAll] = useState(false);
  const awake = useScreenAwake();
  const textRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    sessions.set(recipe.id, { index, timers });
  }, [recipe.id, index, timers]);

  // Tick while a timer runs, and ring once when it is done.
  const running = Object.values(timers).some((t) => !t.rang);
  useEffect(() => {
    if (!running) return;
    const tick = setInterval(() => {
      const at = Date.now();
      setNow(at);
      setTimers((current) => {
        let changed = false;
        const next = { ...current };
        for (const [key, timer] of Object.entries(current)) {
          if (!timer.rang && timer.endsAt <= at) {
            next[Number(key)] = { ...timer, rang: true };
            changed = true;
          }
        }
        if (changed) ring();
        return changed ? next : current;
      });
    }, 500);
    return () => clearInterval(tick);
  }, [running]);

  const go = (next: number) => {
    setIndex(Math.max(0, Math.min(steps.length - 1, next)));
    setShowAll(false);
  };
  useEffect(() => textRef.current?.focus(), [index]);

  const close = () => (canGoBack() ? window.history.back() : route(recipePath(recipe), true));
  const finish = () => {
    sessions.delete(recipe.id);
    close();
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight') go(index + 1);
      if (event.key === 'ArrowLeft') go(index - 1);
      if (event.key === 'Escape') setShowAll(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [index]);

  const step = steps[index];
  const last = index === steps.length - 1;
  const duration = findDuration(step.text);
  const timer = timers[index];
  const left = timer ? (timer.endsAt - now) / 1000 : duration?.seconds ?? 0;

  const toggleTimer = () => {
    if (!duration) return;
    unlockAudio();
    setNow(Date.now());
    setTimers((current) => {
      const next = { ...current };
      if (current[index] && !current[index].rang) delete next[index]; // stop
      else next[index] = { endsAt: Date.now() + duration.seconds * 1000, seconds: duration.seconds, rang: false };
      return next;
    });
  };
  const others = Object.entries(timers)
    .map(([key, t]) => ({ step: Number(key), ...t }))
    .filter((t) => t.step !== index)
    .sort((a, b) => a.endsAt - b.endsAt);
  const dismiss = (key: number) =>
    setTimers((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });

  const ingredients = content.ingredients;
  const used = uniqueLines(step.uses.map((i) => ingredients[i]).filter(Boolean));

  return (
    <div class="kochmodus" role="dialog" aria-label={`Kochmodus: ${recipe.name}`}>
      <header class="kochmodus-kopf">
        <div class="kochmodus-leiste">
          <button type="button" class="kg-iconbtn kochmodus-rund" aria-label="Kochmodus beenden" onClick={close}>
            <KreuzIcon size={22} />
          </button>
          <p class="kochmodus-zaehler" aria-live="polite">Schritt {index + 1} von {steps.length}</p>
          <button type="button" class="kg-iconbtn kochmodus-rund" aria-label="Alle Zutaten anzeigen"
            aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
            <ListeIcon size={22} />
          </button>
        </div>
        <div class="kochmodus-fortschritt" aria-hidden="true">
          {steps.map((_, n) => (
            <button key={n} type="button" tabIndex={-1} class={n <= index ? 'erledigt' : ''} onClick={() => go(n)} />
          ))}
        </div>
        {others.length > 0 && (
          <div class="kochmodus-timerliste">
            {others.map((t) => {
              const done = t.rang;
              return (
                <button key={t.step} type="button" class={`kochmodus-timerchip${done ? ' fertig' : ''}`}
                  onClick={() => (done ? dismiss(t.step) : go(t.step))}>
                  <UhrIcon size={16} />
                  {done ? `Schritt ${t.step + 1}: fertig` : `Schritt ${t.step + 1} · ${clock((t.endsAt - now) / 1000)}`}
                </button>
              );
            })}
          </div>
        )}
      </header>

      <main class="kochmodus-schritt">
        <p class="kochmodus-nummer">{step.group ? `${step.group} · ` : ''}Schritt {index + 1}</p>
        <p class="kochmodus-text" tabIndex={-1} ref={textRef}>
          {duration ? (
            <Fragment>
              {step.text.slice(0, duration.start)}
              <strong>{step.text.slice(duration.start, duration.end)}</strong>
              {step.text.slice(duration.end)}
            </Fragment>
          ) : step.text}
        </p>

        {used.length > 0 && (
          <ul class="kochmodus-zutaten" aria-label="Zutaten für diesen Schritt">
            {used.map((item) => (
              <li key={item.name}>{item.emoji ? `${item.emoji} ` : ''}{item.amount ? `${item.amount} ` : ''}{shortName(item.name)}</li>
            ))}
          </ul>
        )}

        {duration && (
          <div class={`kochmodus-timer${timer?.rang ? ' fertig' : ''}`}>
            <span class="kochmodus-timer-icon" aria-hidden="true"><UhrIcon size={24} /></span>
            <span class="kochmodus-timer-text">
              <span class="text-klein muted">
                {timer?.rang ? 'Timer abgelaufen' : timer ? 'Timer läuft' : `Timer für ${step.text.slice(duration.start, duration.end)}`}
              </span>
              <span class="kochmodus-timer-zeit" role="timer" aria-live="off">{clock(left)}</span>
            </span>
            <button type="button" class={`kg-btn ${timer && !timer.rang ? 'kochmodus-stopp' : 'kg-btn-primaer'}`} onClick={toggleTimer}>
              {timer && !timer.rang ? 'Stopp' : timer ? 'Neu' : 'Start'}
            </button>
          </div>
        )}

        {awake && <p class="kochmodus-wach meta muted">Der Bildschirm bleibt an, solange der Kochmodus offen ist.</p>}
      </main>

      <footer class="kochmodus-fuss">
        <button type="button" class="kg-btn kg-btn-gross kg-btn-sekundaer" disabled={index === 0} onClick={() => go(index - 1)}>
          Zurück
        </button>
        {last ? (
          <button type="button" class="kg-btn kg-btn-gross kg-btn-fertig kochmodus-weiter" onClick={finish}>
            <HakenIcon size={20} />Fertig
          </button>
        ) : (
          <button type="button" class="kg-btn kg-btn-gross kg-btn-primaer kochmodus-weiter" onClick={() => go(index + 1)}>
            Weiter<WeiterIcon size={20} />
          </button>
        )}
      </footer>

      {showAll && (
        <section class="kochmodus-alle" aria-label="Alle Zutaten">
          <div class="kochmodus-alle-kopf">
            <h2 class="titel-block">Alle Zutaten</h2>
            <button type="button" class="kg-iconbtn" aria-label="Schließen" onClick={() => setShowAll(false)}>
              <KreuzIcon size={20} />
            </button>
          </div>
          <ul class="kochmodus-alle-liste">
            {ingredients.map((item, i) =>
              'group' in item ? (
                <li key={i} class="zutaten-gruppe overline">{item.group}</li>
              ) : (
                <li key={i} class={step.uses.includes(i) ? 'jetzt' : ''}>
                  <span aria-hidden="true">{item.emoji ?? '·'}</span>
                  <span class="kochmodus-alle-name">{item.name}</span>
                  {item.amount && <span class="kochmodus-alle-menge">{item.amount}</span>}
                </li>
              ),
            )}
          </ul>
        </section>
      )}
    </div>
  );
}

type Line = Extract<Ingredient, { name: string }>;

/** The same line twice (coriander for the filling and the dip) is shown once. */
function uniqueLines(items: Ingredient[]): Line[] {
  const seen = new Set<string>();
  const lines: Line[] = [];
  for (const item of items) {
    if ('group' in item) continue;
    const key = `${item.amount ?? ''}|${item.name}`;
    if (!seen.has(key)) {
      seen.add(key);
      lines.push(item);
    }
  }
  return lines;
}

/** "Zwiebel, fein gehackt" -> "Zwiebel": the chip names the ingredient, the step says what to do. */
export function shortName(name: string): string {
  return name.split(/[,(]/)[0].trim() || name;
}
