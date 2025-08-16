// Toggle tema claro/oscuro (persiste en localStorage)
(() => {
  const html = document.documentElement;
  const saved = localStorage.getItem('theme');
  if (saved) html.setAttribute('data-bs-theme', saved);

  const btn = document.getElementById('themeToggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const cur = html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-bs-theme', cur);
      localStorage.setItem('theme', cur);
    });
  }

  // Mostrar toasts automáticamente si existen
  document.querySelectorAll('.toast').forEach(t => {
    const toast = new bootstrap.Toast(t, { delay: 4500 });
    toast.show();
  });
})();
