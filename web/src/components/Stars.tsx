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

/** "4,25" */
export function starsValue(value: number): string {
  return value.toLocaleString('de', { maximumFractionDigits: 2 });
}

/** Five stars, filled in quarters. With `onPick`: a tap sets whole stars, − and + fine-tune by a quarter. */
export function Stars({ value, person, onPick, disabled, size = 26 }: Props) {
  const fill = (n: number) => Math.min(1, Math.max(0, value - (n - 1)));
  if (!onPick) {
    return (
      <span class="sterne" role="img"
        aria-label={value ? `${person}: ${starsValue(value)} von 5 Sternen` : `${person}: noch keine Bewertung`}>
        {[1, 2, 3, 4, 5].map((n) => <span key={n} class="stern-platz"><Star fill={fill(n)} size={size} /></span>)}
      </span>
    );
  }
  const pick = (stars: number) => onPick(Math.round(Math.min(5, Math.max(0, stars)) * 4) / 4);
  return (
    <span class="sterne-wahl">
      <span class="sterne" role="group" aria-label={`Bewertung von ${person}`}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" class="stern-knopf" disabled={disabled} aria-pressed={n <= value}
            aria-label={n === value ? `${n} von 5 Sternen, nochmal tippen zum Entfernen` : `${n} von 5 Sternen`}
            onClick={() => pick(n === value ? 0 : n)}>
            <Star fill={fill(n)} size={size} />
          </button>
        ))}
      </span>
      <span class="sterne-fein">
        <button type="button" class="sterne-schritt" disabled={disabled || value <= STEP}
          aria-label="Einen Viertelstern weniger" onClick={() => pick(value - STEP)}>−</button>
        <span class="sterne-wert" aria-live="polite">{value ? starsValue(value) : 'Noch keine'}</span>
        <button type="button" class="sterne-schritt" disabled={disabled || value >= 5}
          aria-label="Einen Viertelstern mehr" onClick={() => pick(value + STEP)}>+</button>
      </span>
    </span>
  );
}

/** The star shape spans 3.5 to 20.5 of 24 units: a quarter star fills a quarter of that, not of the box. */
function Star({ fill, size }: { fill: number; size: number }) {
  const width = fill <= 0 ? 0 : fill >= 1 ? 100 : ((3.5 + fill * 17) / 24) * 100;
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
