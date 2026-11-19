import type { ComponentChildren } from 'preact';

type Props = { size?: number; strokeWidth?: number };

function Svg({ size = 22, strokeWidth = 1.8, children }: Props & { children: ComponentChildren }) {
  return (
    <svg class="kg-icon" aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" stroke-width={strokeWidth} stroke-linecap="round" stroke-linejoin="round">
      {children}
    </svg>
  );
}

export const HeuteIcon = (p: Props) => (
  <Svg {...p}><path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" /></Svg>
);
export const RezepteIcon = (p: Props) => (
  <Svg {...p}>
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z" />
    <path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" />
  </Svg>
);
export const WocheIcon = (p: Props) => (
  <Svg {...p}><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M8 2v4M16 2v4M3 10h18" /></Svg>
);
export const EinkaufIcon = (p: Props) => (
  <Svg {...p}>
    <circle cx="9" cy="20" r="1.5" /><circle cx="18" cy="20" r="1.5" />
    <path d="M2 3h3l2.6 12.4a2 2 0 0 0 2 1.6h8.8a2 2 0 0 0 2-1.6L22 7H6" />
  </Svg>
);
export const SucheIcon = (p: Props) => (
  <Svg {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Svg>
);
export const KachelnIcon = (p: Props) => (
  <Svg {...p}>
    <rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" />
    <rect x="4" y="13" width="7" height="7" rx="1.5" /><rect x="13" y="13" width="7" height="7" rx="1.5" />
  </Svg>
);
export const ListeIcon = (p: Props) => (
  <Svg {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <circle cx="4.5" cy="6" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="4.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="4.5" cy="18" r="1.2" fill="currentColor" stroke="none" />
  </Svg>
);
export const AufklappenIcon = (p: Props) => <Svg strokeWidth={2} {...p}><path d="m6 9 6 6 6-6" /></Svg>;
export const KreuzIcon = (p: Props) => <Svg strokeWidth={2} {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>;
export const ZurueckIcon = (p: Props) => <Svg strokeWidth={2} {...p}><path d="m15 18-6-6 6-6" /></Svg>;
export const WeiterIcon = (p: Props) => <Svg strokeWidth={2} {...p}><path d="m9 18 6-6-6-6" /></Svg>;
export const KochenIcon = (p: Props) => <Svg strokeWidth={2} {...p}><path d="M7 4v16l13-8z" /></Svg>;
export const GekochtIcon = (p: Props) => (
  <Svg {...p}><path d="M5 10h14v5a5 5 0 0 1-5 5h-4a5 5 0 0 1-5-5z" /><path d="M3 10h18" /><path d="M9 6.5c0-1 1-1.5 1-2.5M14 6.5c0-1 1-1.5 1-2.5" /></Svg>
);
export const NeuIcon = (p: Props) => (
  <Svg {...p}><path d="M20 11a8 8 0 0 0-14.6-4.5L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16" /><path d="M20 20v-4h-4" /></Svg>
);
export const UhrIcon = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>;
export const PortionenIcon = (p: Props) => (
  <Svg {...p}><path d="M3 12a9 9 0 0 1 18 0" /><path d="M2 12h20M7 16h10" /></Svg>
);
export const HakenIcon = (p: Props) => <Svg strokeWidth={2.4} {...p}><path d="m5 12 5 5 9-10" /></Svg>;
export const PlusIcon = (p: Props) => <Svg strokeWidth={2.2} {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const ExternIcon = (p: Props) => (
  <Svg strokeWidth={2} {...p}><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></Svg>
);
