/**
 * Counts page changes inside the app, so a back button can use the browser history
 * when there is an app page to go back to, and otherwise goes to a fixed page.
 */
let moves = 0;

export function noteNavigation(): void {
  moves += 1;
}

export function canGoBack(): boolean {
  return moves > 1 && window.history.length > 1;
}
