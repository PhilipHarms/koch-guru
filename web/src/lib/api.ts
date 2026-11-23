import type { PhotoUpload } from './photos';

export type Recipe = {
  id: string;
  name: string;
  link: string;
  source_url: string | null;
  notion_url: string;
  tags: string[];
  origin: string[];
  ingredients: string[];
  this_week: boolean;
  emoji: string | null;
  /** Cover photo through our server, or null. */
  image: string | null;
  created: string | null;
  /** "Zuletzt gekocht", YYYY-MM-DD. */
  last_cooked: string | null;
  /** Stars per person, e.g. { Philip: 4 }. */
  ratings: Record<string, number>;
  /** "Notiz": lines like "19.11.2026 Philip: mehr Chili". */
  note: string | null;
};

export type TextRun = { text: string; href?: string; bold?: boolean; italic?: boolean };

/** Simplified Notion blocks, see koch_guru/page_content.py. */
export type Block =
  | { type: 'heading'; level: 1 | 2 | 3; text: TextRun[] }
  | { type: 'paragraph' | 'quote' | 'toggle'; text: TextRun[]; children?: Block[] }
  | { type: 'bullet' | 'number'; text: TextRun[]; children?: Block[] }
  | { type: 'todo'; text: TextRun[]; checked: boolean }
  | { type: 'callout'; text: TextRun[]; emoji: string | null; children?: Block[] }
  | { type: 'image'; url: string; caption: string }
  | { type: 'link'; url: string; caption: string }
  | { type: 'divider' };

/** `icon` is an image address (Notion's own icons) when the ingredient has no emoji. */
export type Ingredient = { name: string; amount: string | null; emoji: string | null; icon?: string } | { group: string };
/** `uses`: positions in `ingredients` of what the step mentions. */
export type Step = { text: string; uses?: number[] } | { group: string };

export type RecipeContent = {
  minutes: number | null;
  servings: string | null;
  ingredients: Ingredient[];
  steps: Step[];
  blocks: Block[];
};

export type ChatTurn = { role: 'user' | 'assistant'; content: string };
export type Suggestions = {
  message: string;
  suggestions: { recipe: Recipe; reason: string }[];
  /** The answer as text, to send back as history with a follow-up wish. */
  history_entry: string;
};

/** A recipe idea from "Woche planen"; `quick` when it is done fast. */
export type WeekSuggestion = { recipe: Recipe; reason: string; quick: boolean };

export type GeneratedIngredient = {
  line: string;
  amount: string | null;
  name: string;
  /** The ingredient in the ingredients database, or the name it would get there. */
  zutat: string;
  emoji: string | null;
  /** 'group' is a heading like "Für die Salsa:", shown without a checkbox. */
  status: 'linked' | 'existing' | 'new' | 'group';
  staple: boolean;
  include: boolean;
  /** Supermarket aisle (tag in Notion) for a new ingredient. */
  aisle?: string | null;
};

export type GeneratedRecipe = {
  source: string;
  url: string | null;
  /** Recipe photo of the linked page, offered as the Notion cover. */
  image: string | null;
  servings: string | null;
  minutes: number | null;
  ingredients: GeneratedIngredient[];
  steps: string[];
  /** Only when generating again: what the new version replaces on the Notion page. */
  replaces?: { info: boolean; ingredients: number; steps: number };
  /** Only when generating again: linked ingredients the new version does not use. */
  unlink?: { id: string; name: string }[];
};

export type GeneratedSave = {
  url: string | null;
  servings: string | null;
  minutes: number | null;
  ingredients: { line: string; zutat: string; emoji: string | null; link: boolean; aisle?: string | null }[];
  steps: string[];
  cover: string | null;
  replace_cover?: boolean;
  /** Replace the earlier generated ingredients and steps. */
  replace?: boolean;
  /** Ingredient ids to unlink from the recipe. */
  unlink?: string[];
  /** Corrected link for the Link field in Notion. */
  new_link?: string | null;
};

/** A recipe read by "Rezept hinzufügen", not saved yet. */
export type ImportPreview = GeneratedRecipe & {
  draft_id: string;
  name: string;
  icon: string | null;
  /** Chosen tags; `tag_options` are all tags in Notion. */
  tags: string[];
  tag_options: string[];
  /** Cookbook, when the photo shows one. */
  origin: string[];
  /** e.g. "chefkoch.de"; null for photos. */
  site: string | null;
  from_photo: boolean;
  /** A recipe of the same name already in the collection. */
  similar: Recipe | null;
};

export type ImportSave = {
  name: string;
  tags: string[];
  servings: string | null;
  ingredients: GeneratedSave['ingredients'];
  steps: string[];
  cover: boolean;
};

/** A field like Tags or Kochbuch: its options in Notion, and whether several can be chosen. */
export type ChoiceField = { options: string[]; multiple: boolean } | null;
export type RecipeFields = { tags: ChoiceField; origin: ChoiceField; link: boolean };
export type RecipeChanges = Partial<{ name: string; emoji: string | null; tags: string[]; origin: string[]; link: string | null }>;

/** Ingredients and steps as plain lines, if the page has "Zutaten" and "Zubereitung". */
export type EditContent = {
  editable: boolean;
  minutes: number | null;
  servings: string | null;
  ingredients: string[];
  steps: string[];
};
export type IngredientCheck = { lines: GeneratedIngredient[]; unlink: { id: string; name: string }[] };
export type ContentSave = {
  minutes: number | null;
  servings: string | null;
  ingredients: string[];
  steps: string[];
  link: { zutat: string; emoji: string | null; aisle: string | null }[];
  unlink: string[];
};

export type RecipeList = {
  recipes: Recipe[];
  week_supported: boolean;
  /** Who can rate, in order. */
  people: string[];
  cooked_supported: boolean;
};

/** One line of the shopping list: an ingredient page in Notion. `done` is its "Bought" checkbox. */
export type ShoppingItem = {
  id: string;
  name: string;
  /** Emoji, or image address of a Notion icon. */
  icon: string | null;
  amount: string | null;
  done: boolean;
  /** Other recipes of the week that need it too. */
  also: string[];
  /** Supermarket aisle from the ingredient's tags in Notion. */
  aisle: string | null;
};

export type ShoppingList = {
  groups: { recipe_id: string; items: ShoppingItem[] }[];
  extras: ShoppingItem[];
  open: number;
  can_check: boolean;
  can_add: boolean;
  /** Aisles in the order of the tags in Notion. */
  aisles: string[];
};
export type Me = { user: string; name: string };

export class NotSignedIn extends Error {}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    ...init,
  });
  if (response.status === 401) throw new NotSignedIn();
  if (!response.ok) {
    let message = 'Das hat nicht geklappt. Bitte versuch es gleich noch einmal.';
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') message = body.detail;
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export const api = {
  me: () => request<Me>('/api/me'),
  recipes: () => request<RecipeList>('/api/recipes'),
  content: (id: string) => request<RecipeContent>(`/api/recipes/${encodeURIComponent(id)}/content`),
  /** For each step (headings left out) the positions in `ingredients` it uses, read by KochGuru. */
  stepLinks: (id: string) => request<{ uses: number[][] }>(`/api/recipes/${encodeURIComponent(id)}/step-links`),
  suggest: (wish: string, history: ChatTurn[]) =>
    request<Suggestions>('/api/suggest', { method: 'POST', body: JSON.stringify({ wish, history }) }),
  generate: (id: string, again?: { link: string | null }) =>
    request<GeneratedRecipe>(`/api/recipes/${encodeURIComponent(id)}/generate`, {
      method: 'POST',
      ...(again ? { body: JSON.stringify({ again: true, link: again.link }) } : {}),
    }),
  saveGenerated: (id: string, body: GeneratedSave) =>
    request<{ recipe: Recipe; not_created: string[] }>(`/api/recipes/${encodeURIComponent(id)}/generate/save`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  importRecipe: (body: { url?: string; photos?: PhotoUpload[]; caption?: string }) =>
    request<ImportPreview | { existing: Recipe }>('/api/import', { method: 'POST', body: JSON.stringify(body) }),
  saveImport: (draftId: string, body: ImportSave) =>
    request<{ recipe: Recipe; not_created: string[] }>(`/api/import/${encodeURIComponent(draftId)}/save`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  editContent: (id: string) => request<EditContent>(`/api/recipes/${encodeURIComponent(id)}/edit-content`),
  checkIngredients: (id: string, ingredients: string[]) =>
    request<IngredientCheck>(`/api/recipes/${encodeURIComponent(id)}/edit-content/check`, {
      method: 'POST',
      body: JSON.stringify({ ingredients }),
    }),
  saveContent: (id: string, body: ContentSave) =>
    request<{ recipe: Recipe; not_created: string[] }>(`/api/recipes/${encodeURIComponent(id)}/content`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  missingPhotos: () => request<{ with_link: Recipe[]; without_link: number }>('/api/photos/missing'),
  findPhotos: (ids: string[]) =>
    request<{ id: string; image: string | null }[]>('/api/photos/find', { method: 'POST', body: JSON.stringify({ ids }) }),
  applyPhotos: (items: { id: string; image: string }[]) =>
    request<{ recipes: Recipe[]; failed: string[] }>('/api/photos/apply', { method: 'POST', body: JSON.stringify({ items }) }),
  recipeFields: () => request<RecipeFields>('/api/recipe-fields'),
  updateRecipe: (id: string, changes: RecipeChanges) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  removeCover: (id: string) => request<Recipe>(`/api/recipes/${encodeURIComponent(id)}/cover`, { method: 'DELETE' }),
  setCover: (id: string, photo: PhotoUpload) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}/cover`, { method: 'PUT', body: JSON.stringify(photo) }),
  shoppingList: () => request<ShoppingList>('/api/shopping-list'),
  setBought: (id: string, bought: boolean) =>
    request<ShoppingItem>(`/api/ingredients/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ bought }),
    }),
  addExtra: (name: string) =>
    request<ShoppingItem>('/api/extras', { method: 'POST', body: JSON.stringify({ name }) }),
  /** `day`: cooked on (today when missing); `later`: noted afterwards, not at the end of the cooking mode. */
  cooked: (id: string, body: { stars?: number | null; note?: string | null; day?: string; later?: boolean }) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}/cooked`, { method: 'POST', body: JSON.stringify(body) }),
  rate: (id: string, stars: number) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}/rating`, { method: 'PUT', body: JSON.stringify({ stars }) }),
  clearWeek: () => request<{ cleared: number }>('/api/week/clear', { method: 'POST' }),
  /** Ideas for the week; `keep` are already chosen, `exclude` were shown before. */
  planWeek: (body: { count: number; keep?: string[]; exclude?: string[] }) =>
    request<{ suggestions: WeekSuggestion[] }>('/api/week/plan', { method: 'POST', body: JSON.stringify(body) }),
  setThisWeek: (id: string, thisWeek: boolean) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ this_week: thisWeek }),
    }),
};
