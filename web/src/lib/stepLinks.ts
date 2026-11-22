import { api, type RecipeContent } from './api';

const asked = new Map<string, Promise<number[][]>>();

/** Changes with the ingredients and steps, so an edited recipe is read again. */
function keyOf(id: string, content: RecipeContent): string {
  const text = JSON.stringify([
    content.ingredients.map((i) => ('group' in i ? `# ${i.group}` : `${i.amount ?? ''} ${i.name}`)),
    content.steps.map((s) => ('group' in s ? `# ${s.group}` : s.text)),
  ]);
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return `${id}:${text.length}:${hash}`;
}

/**
 * What each step uses, read by KochGuru: asked once per recipe content, so the recipe page
 * can ask ahead and the cooking mode has the answer when it opens. A failed answer is asked again.
 */
export function stepLinks(id: string, content: RecipeContent): Promise<number[][]> {
  const key = keyOf(id, content);
  let answer = asked.get(key);
  if (!answer) {
    answer = api.stepLinks(id).then((r) => r.uses);
    answer.catch(() => asked.delete(key));
    asked.set(key, answer);
  }
  return answer;
}
