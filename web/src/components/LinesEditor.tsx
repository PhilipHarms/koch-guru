import { useLayoutEffect, useRef } from 'preact/hooks';
import { KreuzIcon, PlusIcon } from './icons';

export type Line = { key: number; text: string };

let counter = 0;
export const toLines = (texts: string[]): Line[] => texts.map((text) => ({ key: ++counter, text }));
export const newLine = (): Line => ({ key: ++counter, text: '' });

/** Grows with its text, so a long step stays readable. */
function grow(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

/** Editable list of lines: one field per ingredient or step, with remove and add. */
export function LinesEditor({ lines, onChange, numbered, label, addLabel, placeholder, disabled }: {
  lines: Line[];
  onChange: (lines: Line[]) => void;
  numbered: boolean;
  /** Name of one line for screen readers, e.g. "Zutat". */
  label: string;
  addLabel: string;
  placeholder: string;
  disabled: boolean;
}) {
  const list = useRef<HTMLOListElement>(null);
  const focusKey = useRef<number | null>(null);

  useLayoutEffect(() => {
    list.current?.querySelectorAll('textarea').forEach((el) => grow(el as HTMLTextAreaElement));
    if (focusKey.current !== null) {
      (list.current?.querySelector(`[data-key="${focusKey.current}"]`) as HTMLElement | null)?.focus();
      focusKey.current = null;
    }
  });

  const set = (key: number, text: string) => onChange(lines.map((l) => (l.key === key ? { ...l, text } : l)));
  const remove = (key: number) => onChange(lines.filter((l) => l.key !== key));
  const add = (after?: number) => {
    const line = newLine();
    focusKey.current = line.key;
    const index = after === undefined ? lines.length : lines.findIndex((l) => l.key === after) + 1;
    onChange([...lines.slice(0, index), line, ...lines.slice(index)]);
  };

  return (
    <div class="zeilen">
      <ol ref={list} class={`zeilen-liste${numbered ? ' zeilen-nummeriert' : ''}`}>
        {lines.map((line, index) => (
          <li key={line.key} class="zeile">
            {numbered && <span class="schritt-nummer" aria-hidden="true">{index + 1}</span>}
            {numbered ? (
              <textarea data-key={line.key} rows={1} value={line.text} disabled={disabled} placeholder={placeholder}
                aria-label={`${label} ${index + 1}`}
                onInput={(e) => { grow(e.target as HTMLTextAreaElement); set(line.key, (e.target as HTMLTextAreaElement).value); }} />
            ) : (
              <input data-key={line.key} type="text" value={line.text} disabled={disabled} placeholder={placeholder}
                aria-label={`${label} ${index + 1}`} enterKeyHint="next"
                onInput={(e) => set(line.key, (e.target as HTMLInputElement).value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(line.key); } }} />
            )}
            <button type="button" class="kg-iconbtn zeile-weg" aria-label={`${label} ${index + 1} entfernen`}
              disabled={disabled} onClick={() => remove(line.key)}>
              <KreuzIcon size={16} />
            </button>
          </li>
        ))}
      </ol>
      <button type="button" class="kg-btn import-nochmal zeilen-neu" disabled={disabled} onClick={() => add()}>
        <PlusIcon size={18} />{addLabel}
      </button>
    </div>
  );
}
