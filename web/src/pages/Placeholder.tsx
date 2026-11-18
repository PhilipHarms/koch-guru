export function PlaceholderPage({ title, text }: { title: string; text: string }) {
  return (
    <main class="page">
      <header class="page-header">
        <h1 class="titel-seite">{title}</h1>
      </header>
      <p class="page-pad text-klein muted">{text}</p>
    </main>
  );
}
