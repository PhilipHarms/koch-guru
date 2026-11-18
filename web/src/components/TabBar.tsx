import { useLocation } from 'preact-iso';
import { EinkaufIcon, HeuteIcon, RezepteIcon, WocheIcon } from './icons';

const TABS = [
  { href: '/', label: 'Heute', Icon: HeuteIcon },
  { href: '/rezepte', label: 'Rezepte', Icon: RezepteIcon },
  { href: '/woche', label: 'Woche', Icon: WocheIcon },
  { href: '/einkauf', label: 'Einkauf', Icon: EinkaufIcon },
];

export function TabBar() {
  const { path } = useLocation();
  return (
    <nav class="kg-nav app-nav" aria-label="Hauptnavigation" style={{ gridTemplateColumns: `repeat(${TABS.length}, minmax(0, 1fr))` }}>
      {TABS.map(({ href, label, Icon }) => (
        <a href={href} aria-current={path === href ? 'page' : undefined} key={href}>
          <Icon size={26} />
          {label}
        </a>
      ))}
    </nav>
  );
}
