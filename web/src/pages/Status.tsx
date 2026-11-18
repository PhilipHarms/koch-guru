/** Full-screen states on the brand colour: signed out, loading, error. */
export function BrandScreen({ text, action }: { text: string; action?: { label: string; onClick: () => void } }) {
  return (
    <main class="brand-screen">
      <img src="/icons/app-icon-512.png" alt="" width="160" height="160" />
      <h1>KochGuru</h1>
      <p>{text}</p>
      {action && (
        <button type="button" class="kg-btn brand-screen-button" onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </main>
  );
}
