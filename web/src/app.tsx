import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import { LocationProvider, Route, Router, useLocation } from 'preact-iso';
import { api, NotSignedIn, type Me, type Recipe } from './lib/api';
import { DataContext, type AppData } from './lib/data';
import { noteNavigation } from './lib/nav';
import { TabBar } from './components/TabBar';
import { RecipesRoute } from './pages/Recipes';
import { RecipeRoute } from './pages/Recipe';
import { WeekRoute } from './pages/Week';
import { TodayRoute } from './pages/Today';
import { PlaceholderPage } from './pages/Placeholder';
import { BrandScreen } from './pages/Status';

type State =
  | { kind: 'loading' }
  | { kind: 'signed-out' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; me: Me; recipes: Recipe[]; weekSupported: boolean };

// Route components live outside App, so that a data update re-renders them instead of
// mounting them anew (which would reload a recipe page and lose its state).
function ShoppingRoute() {
  return <PlaceholderPage title="Einkaufsliste" text="Die Einkaufsliste kommt, sobald die Zutaten-Datenbank angebunden ist." />;
}

function NotFoundRoute() {
  return <PlaceholderPage title="Nicht gefunden" text="Diese Seite gibt es nicht." />;
}

function NavigationCounter() {
  const { url } = useLocation();
  useEffect(() => noteNavigation(), [url]);
  return null;
}

export function App() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  const loadAll = useCallback(async () => {
    try {
      const [me, list] = await Promise.all([api.me(), api.recipes()]);
      setState({ kind: 'ready', me, recipes: list.recipes, weekSupported: list.week_supported });
    } catch (error) {
      if (error instanceof NotSignedIn) setState({ kind: 'signed-out' });
      else setState({ kind: 'error', message: error instanceof Error ? error.message : 'Unbekannter Fehler' });
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const updateRecipe = useCallback((updated: Recipe) => {
    setState((s) => (s.kind === 'ready' ? { ...s, recipes: s.recipes.map((r) => (r.id === updated.id ? updated : r)) } : s));
  }, []);

  const weekCleared = useCallback(() => {
    setState((s) => (s.kind === 'ready' ? { ...s, recipes: s.recipes.map((r) => (r.this_week ? { ...r, this_week: false } : r)) } : s));
  }, []);

  const data = useMemo<AppData | null>(
    () => (state.kind === 'ready'
      ? { me: state.me, recipes: state.recipes, weekSupported: state.weekSupported, updateRecipe, weekCleared }
      : null),
    [state, updateRecipe, weekCleared],
  );

  if (state.kind === 'loading') return <BrandScreen text="Rezepte werden geladen …" />;
  if (state.kind === 'signed-out') return <BrandScreen text="Bitte öffne deinen persönlichen Anmeldelink." />;
  if (state.kind === 'error') {
    return <BrandScreen text={state.message} action={{ label: 'Nochmal versuchen', onClick: () => { setState({ kind: 'loading' }); loadAll(); } }} />;
  }

  return (
    <DataContext.Provider value={data}>
      <LocationProvider>
        <NavigationCounter />
        <div class="app">
          <Router>
            <Route path="/" component={TodayRoute} />
            <Route path="/rezepte" component={RecipesRoute} />
            <Route path="/rezepte/:id" component={RecipeRoute} />
            <Route path="/woche" component={WeekRoute} />
            <Route path="/einkauf" component={ShoppingRoute} />
            <Route default component={NotFoundRoute} />
          </Router>
          <TabBar />
        </div>
      </LocationProvider>
    </DataContext.Provider>
  );
}
