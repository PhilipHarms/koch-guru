import { createContext } from 'preact';
import { useContext } from 'preact/hooks';
import type { Me, Recipe } from './api';

export type AppData = {
  me: Me;
  recipes: Recipe[];
  weekSupported: boolean;
  /** Who can rate recipes, e.g. ["Philip", "Charlotte"]; empty without the fields in Notion. */
  people: string[];
  cookedSupported: boolean;
  /** Replace one recipe after the server confirmed a change. */
  updateRecipe: (recipe: Recipe) => void;
  /** A recipe that was just created in Notion. */
  addRecipe: (recipe: Recipe) => void;
  /** Untick "This Week?" everywhere after the server cleared the list. */
  weekCleared: () => void;
};

export const DataContext = createContext<AppData | null>(null);

export function useData(): AppData {
  const data = useContext(DataContext);
  if (!data) throw new Error('DataContext fehlt');
  return data;
}
