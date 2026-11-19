import type { GeneratedIngredient } from '../lib/api';

export function initialOf(name: string): string {
  return name.match(/\p{L}/u)?.[0].toLocaleUpperCase('de') ?? '·';
}

function statusText(item: GeneratedIngredient, include: boolean): string {
  if (item.status === 'linked') return 'schon verknüpft';
  if (!include) return item.staple ? 'immer da, wird nicht verknüpft' : 'wird nicht verknüpft';
  if (item.status === 'existing') return `verknüpft mit „${item.zutat}“`;
  return `wird als „${item.zutat}“ neu angelegt${item.aisle ? `, Abteilung ${item.aisle}` : ''}`;
}

/** Ingredient lines of a read recipe; ticked ones get linked to the ingredients database. */
export function IngredientChoice({ items, include, disabled, onToggle }: {
  items: GeneratedIngredient[];
  include: boolean[];
  disabled: boolean;
  onToggle: (index: number) => void;
}) {
  return (
    <ul class="zutaten">
      {items.map((item, index) => item.status === 'group' ? (
        <li key={index} class="zutaten-gruppe overline">{item.name}</li>
      ) : (
        <li key={index} class="zutat generiert-zutat">
          <label>
            <input type="checkbox" checked={include[index]} disabled={item.status === 'linked' || disabled}
              onChange={() => onToggle(index)} />
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
  );
}
