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
  created: string | null;
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
  setThisWeek: (id: string, thisWeek: boolean) =>
    request<Recipe>(`/api/recipes/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify({ this_week: thisWeek }),
    }),
};
