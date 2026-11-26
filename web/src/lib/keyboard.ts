/** Fields that open the on-screen keyboard. */
const TYPING =
  'input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="file"])' +
  ':not([type="button"]):not([type="submit"]), textarea, [contenteditable=""], [contenteditable="true"]';

/**
 * While typing on a phone, `data-tastatur` is set on <html>.
 *
 * iOS moves the visible part of the page up when the keyboard opens, and bars fixed to the
 * bottom (the tab bar, the "+" button) move with it into the middle of the screen. The CSS
 * hides them while the attribute is set. With a mouse there is no on-screen keyboard.
 */
export function watchKeyboard(): void {
  if (!window.matchMedia('(pointer: coarse)').matches) return;
  const update = () => {
    const field = document.activeElement;
    const typing = field instanceof HTMLElement && field.matches(TYPING) && !(field as HTMLInputElement).readOnly;
    document.documentElement.toggleAttribute('data-tastatur', typing);
  };
  document.addEventListener('focusin', update);
  // From one field to the next, focus leaves before it arrives: look once it has settled.
  document.addEventListener('focusout', () => setTimeout(update, 0));
}
