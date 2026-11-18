import { useCallback, useEffect, useState } from 'preact/hooks';
import { LocationProvider, Route, Router } from 'preact-iso';
import { api, NotSignedIn, type Me, type Recipe } from './lib/api';
import { TabBar } from './components/TabBar';
import { RecipesPage } from './pages/Recipes';
import { PlaceholderPage } from './pages/Placeholder';
import { BrandScreen } from './pages/Status';

type State =
  | { kind: 'loading' }
  | { kind: 'signed-out' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; me: Me; recipes: Recipe[] };

export function App() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  const loadAll = useCallback(async () => {
    try {
      const [me, list] = await Promise.all([api.me(), api.recipes()]);
      setState({ kind: 'ready', me, recipes: list.recipes });
    } catch (error) {
      if (error instanceof NotSignedIn) setState({ kind: 'signed-out' });
      else setState({ kind: 'error', message: error instanceof Error ? error.message : 'Unbekannter Fehler' });
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  if (state.kind === 'loading') return <BrandScreen text="Rezepte werden geladen …" />;
  if (state.kind === 'signed-out') return <BrandScreen text="Bitte öffne deinen persönlichen Anmeldelink." />;
  if (state.kind === 'error') {
    return <BrandScreen text={state.message} action={{ label: 'Nochmal versuchen', onClick: () => { setState({ kind: 'loading' }); loadAll(); } }} />;
  }

  const { me, recipes } = state;
  return (
    <LocationProvider>
      <div class="app">
        <Router>
          <Route path="/" component={() => (
            <PlaceholderPage title={`Hallo ${me.name}`} text="Hier stehen bald die Suche, ein Vorschlag für heute und eure Wochenliste." />
          )} />
          <Route path="/rezepte" component={() => <RecipesPage recipes={recipes} />} />
          <Route path="/woche" component={() => (
            <PlaceholderPage title="Diese Woche" text="Die Wochenliste kommt mit dem nächsten Schritt. Bis dahin geht sie über den Telegram-Bot." />
          )} />
          <Route path="/einkauf" component={() => (
            <PlaceholderPage title="Einkaufsliste" text="Die Einkaufsliste kommt, sobald die Zutaten-Datenbank angebunden ist." />
          )} />
          <Route default component={() => <PlaceholderPage title="Nicht gefunden" text="Diese Seite gibt es nicht." />} />
        </Router>
        <TabBar />
      </div>
    </LocationProvider>
  );
}
