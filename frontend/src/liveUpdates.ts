export function pollWhileVisible(refresh: () => Promise<void>) {
  let pending = false;
  async function update() {
    if (document.hidden || pending) return;
    pending = true;
    try { await refresh(); }
    finally { pending = false; }
  }
  const timer = window.setInterval(update, 5000);
  document.addEventListener('visibilitychange', update);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', update);
  };
}
