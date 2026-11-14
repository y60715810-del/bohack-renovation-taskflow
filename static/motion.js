// Keep the real collaboration UI interactive: the rebuild effect is opt-in
// and isolated to a disposable frame. No third-party network calls.
const dialog = document.querySelector('#collaboration-story');
const scene = document.querySelector('#story-scene');
let opener;
document.addEventListener('click', event => {
  const button = event.target.closest('[data-open-story]');
  if (button) {
    opener = button;
    const frame = document.createElement('iframe');
    frame.title = '需求、设计、施工与交付的四方协作演示';
    frame.src = '/static/collaboration-scene.html';
    scene.replaceChildren(frame);
    dialog.showModal();
  }
  if (event.target.closest('[data-close-story]')) dialog.close();
});
dialog.addEventListener('close', () => {
  scene.replaceChildren();
  if (opener?.isConnected) opener.focus();
});
// Native directory controls keep the original role-switch handler untouched.
document.addEventListener('pointerdown', event => {
  document.querySelectorAll('.role-directory[open]').forEach(menu => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  document.querySelectorAll('.role-directory[open]').forEach(menu => {
    menu.open = false;
    menu.querySelector('summary').focus();
  });
});
