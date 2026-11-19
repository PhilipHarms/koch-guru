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

export function Stars({ value, person, onPick, disabled, size = 26 }: Props) {
  if (!onPick) {
    return (
      <span class="sterne" role="img" aria-label={value ? `${person}: ${value} von 5 Sternen` : `${person}: noch keine Bewertung`}>
        {[1, 2, 3, 4, 5].map((n) => <span key={n} class="stern-platz"><Star filled={n <= value} size={size} /></span>)}
      </span>
    );
  }
  return (
    <span class="sterne" role="group" aria-label={`Bewertung von ${person}`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" class="stern-knopf" disabled={disabled} aria-pressed={n <= value}
          aria-label={n === value ? `${n} von 5 Sternen, nochmal tippen zum Entfernen` : `${n} von 5 Sternen`}
          onClick={() => onPick(n === value ? 0 : n)}>
          <Star filled={n <= value} size={size} />
        </button>
      ))}
    </span>
  );
}

function Star({ filled, size }: { filled: boolean; size: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" class={filled ? 'stern voll' : 'stern'}>
      <path d={PATH} />
    </svg>
  );
}
