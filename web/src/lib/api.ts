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
export type Step = { text: string } | { group: string };

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
};

export type GeneratedSave = {
  url: string | null;
  servings: string | null;
  minutes: number | null;
  ingredients: { line: string; zutat: string; emoji: string | null; link: boolean }[];
  steps: string[];
  cover: string | null;
};

export type RecipeList = { recipes: Recipe[]; week_supported: boolean };
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
  suggest: (wish: string, history: ChatTurn[]) =>
    request<Suggestions>('/api/suggest', { method: 'POST', body: JSON.stringify({ wish, history }) }),
  generate: (id: string) =>
    request<GeneratedRecipe>(`/api/recipes/${encodeURIComponent(id)}/generate`, { method: 'POST' }),
  saveGenerated: (id: string, body: GeneratedSave) =>
    request<{ recipe: Recipe; not_created: string[] }>(`/api/recipes/${encodeURIComponent(id)}/generate/save`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  clearWeek: () => request<{ cleared: number }>('/api/week/clear', { method: 'POST' }),
  setThisWeek: (id: string, thisWeek: boolean) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ this_week: thisWeek }),
    }),
};
