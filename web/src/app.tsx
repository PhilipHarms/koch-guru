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
import { ShoppingRoute } from './pages/Shopping';
import { CookRoute } from './pages/Cook';
import { ImportRoute } from './pages/Import';
import { EditRoute } from './pages/Edit';
import { PlaceholderPage } from './pages/Placeholder';
import { BrandScreen } from './pages/Status';

type State =
  | { kind: 'loading' }
  | { kind: 'signed-out' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; me: Me; recipes: Recipe[]; weekSupported: boolean; people: string[]; cookedSupported: boolean };

// Route components live outside App, so that a data update re-renders them instead of
// mounting them anew (which would reload a recipe page and lose its state).
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
      setState({
        kind: 'ready', me, recipes: list.recipes, weekSupported: list.week_supported,
        people: list.people ?? [], cookedSupported: Boolean(list.cooked_supported),
      });
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

  const addRecipe = useCallback((added: Recipe) => {
    setState((s) => (s.kind === 'ready' ? { ...s, recipes: [added, ...s.recipes.filter((r) => r.id !== added.id)] } : s));
  }, []);

  const weekCleared = useCallback(() => {
    setState((s) => (s.kind === 'ready' ? { ...s, recipes: s.recipes.map((r) => (r.this_week ? { ...r, this_week: false } : r)) } : s));
  }, []);

  const data = useMemo<AppData | null>(
    () => (state.kind === 'ready'
      ? {
          me: state.me, recipes: state.recipes, weekSupported: state.weekSupported,
          people: state.people, cookedSupported: state.cookedSupported, updateRecipe, addRecipe, weekCleared,
        }
      : null),
    [state, updateRecipe, addRecipe, weekCleared],
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
            <Route path="/rezepte/neu" component={ImportRoute} />
            <Route path="/rezepte/:id" component={RecipeRoute} />
            <Route path="/rezepte/:id/kochen" component={CookRoute} />
            <Route path="/rezepte/:id/bearbeiten" component={EditRoute} />
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
