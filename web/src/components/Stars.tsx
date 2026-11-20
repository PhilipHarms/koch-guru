import { useRef, useState } from 'preact/hooks';

type Props = {
  value: number;
  /** Who the stars belong to, for screen readers. */
  person: string;
  /** Without it the stars are only shown. Picking the current value again removes the rating. */
  onPick?: (stars: number) => void;
  disabled?: boolean;
  size?: number;
};

const PATH = 'M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z';
const STEP = 0.25;
// The star shape spans 3.5 to 20.5 of its 24 units: fill and touch are measured on the shape, not its box.
const SHAPE_FROM = 3.5 / 24;
const SHAPE_WIDTH = 17 / 24;

/** "4,25" */
export function starsValue(value: number): string {
  return value.toLocaleString('de', { maximumFractionDigits: 2 });
}

const quarter = (value: number) => Math.min(5, Math.max(STEP, Math.ceil(value / STEP - 1e-9) * STEP));

/**
 * Five stars, filled in quarters. With `onPick` they are a slider: where you tap or let go sets
 * the stars in quarters (the right edge of a star = the whole star), sliding shows the value as
 * you go. Arrow keys change it by a quarter.
 */
export function Stars({ value, person, onPick, disabled, size = 26 }: Props) {
  const row = useRef<HTMLSpanElement>(null);
  const startX = useRef(0);
  const moved = useRef(false);
  const [sliding, setSliding] = useState<number | null>(null);
  const shown = sliding ?? value;
  const fill = (n: number) => Math.min(1, Math.max(0, shown - (n - 1)));
  const stars = [1, 2, 3, 4, 5].map((n) => (
    <span key={n} class="stern-platz"><Star fill={fill(n)} size={size} /></span>
  ));

  if (!onPick) {
    return (
      <span class="sterne" role="img"
        aria-label={value ? `${person}: ${starsValue(value)} von 5 Sternen` : `${person}: noch keine Bewertung`}>
        {stars}
      </span>
    );
  }

  /** Stars under a finger: which slot, and how far across its star shape. */
  const at = (clientX: number): number => {
    const slots = row.current ? [...row.current.children] as HTMLElement[] : [];
    for (let i = 0; i < slots.length; i++) {
      const box = slots[i].getBoundingClientRect();
      if (clientX < box.right || i === slots.length - 1) {
        const across = (clientX - box.left) / box.width;
        return quarter(i + (across - SHAPE_FROM) / SHAPE_WIDTH);
      }
    }
    return value;
  };
  // Tapping the current value removes the rating; sliding back to it keeps it.
  const choose = (stars: number, tapped: boolean) => {
    if (stars === value) {
      if (tapped) onPick(0);
      return;
    }
    onPick(stars);
  };

  return (
    <span ref={row} class={`sterne sterne-regler${disabled ? ' aus' : ''}`} role="slider" tabIndex={disabled ? -1 : 0}
      aria-label={`Bewertung von ${person}`} aria-valuemin={0} aria-valuemax={5} aria-valuenow={value}
      aria-valuetext={value ? `${starsValue(value)} von 5 Sternen` : 'noch keine Bewertung'}
      aria-disabled={disabled || undefined}
      onPointerDown={(e) => {
        if (disabled || e.button > 0) return;
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        startX.current = e.clientX;
        moved.current = false;
        setSliding(at(e.clientX));
      }}
      onPointerMove={(e) => {
        if (sliding === null) return;
        if (Math.abs(e.clientX - startX.current) >= 8) moved.current = true;
        setSliding(at(e.clientX));
      }}
      onPointerUp={(e) => {
        if (sliding === null) return;
        setSliding(null);
        choose(at(e.clientX), !moved.current);
      }}
      onPointerCancel={() => setSliding(null)}
      onKeyDown={(e) => {
        if (disabled) return;
        const next = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? Math.min(5, value + STEP)
          : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? Math.max(0, value - STEP)
          : e.key === 'Home' ? 0 : e.key === 'End' ? 5 : null;
        if (next === null) return;
        e.preventDefault();
        onPick(next);
      }}>
      {stars}
      {sliding !== null && <span class="sterne-blase" aria-hidden="true">{starsValue(sliding)}</span>}
    </span>
  );
}

function Star({ fill, size }: { fill: number; size: number }) {
  const width = fill <= 0 ? 0 : fill >= 1 ? 100 : (SHAPE_FROM + fill * SHAPE_WIDTH) * 100;
  return (
    <span class="stern-teil" style={{ width: `${size}px`, height: `${size}px` }}>
      <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" class="stern"><path d={PATH} /></svg>
      {width > 0 && (
        <span class="stern-fuellung" style={{ width: `${width}%` }}>
          <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" class="stern voll"><path d={PATH} /></svg>
        </span>
      )}
    </span>
  );
}
