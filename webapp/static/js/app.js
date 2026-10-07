// Icones Lucide : au chargement, puis apres chaque mise a jour partielle par HTMX.
function renderIcons() { if (window.lucide) window.lucide.createIcons(); }
document.addEventListener("DOMContentLoaded", renderIcons);
document.addEventListener("htmx:afterSwap", renderIcons);
