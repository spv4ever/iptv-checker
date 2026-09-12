import { parseIptvList, toCsv } from './parser.js';

const source = document.querySelector('#source');
const results = document.querySelector('#results');
const emptyState = document.querySelector('#emptyState');
const actions = document.querySelector('#resultActions');
const badge = document.querySelector('#validBadge');
const lineCount = document.querySelector('#lineCount');
const toast = document.querySelector('#toast');
let currentEntries = [];

function updateCount() {
  const count = source.value ? source.value.split(/\r?\n/).length : 0;
  lineCount.textContent = `${count} ${count === 1 ? 'línea' : 'líneas'}`;
}

function render(entries) {
  currentEntries = entries;
  badge.textContent = `${entries.length} ${entries.length === 1 ? 'válida' : 'válidas'}`;
  emptyState.hidden = entries.length > 0;
  results.hidden = entries.length === 0;
  actions.hidden = entries.length === 0;
  results.replaceChildren(...entries.map((entry, index) => {
    const article = document.createElement('article');
    article.className = 'result-card';
    const fields = [
      ['SERVIDOR', entry.server], ['USUARIO', entry.username], ['CONTRASEÑA', entry.password]
    ];
    const number = document.createElement('span'); number.className = 'result-number'; number.textContent = String(index + 1).padStart(2, '0');
    article.append(number);
    for (const [label, value] of fields) {
      const field = document.createElement('div');
      const title = document.createElement('small'); title.textContent = label;
      const text = document.createElement('strong'); text.textContent = value;
      field.append(title, text); article.append(field);
    }
    return article;
  }));
}

function showToast(message) {
  toast.textContent = message; toast.classList.add('show');
  window.setTimeout(() => toast.classList.remove('show'), 2200);
}

source.addEventListener('input', updateCount);
document.querySelector('#clearBtn').addEventListener('click', () => { source.value = ''; updateCount(); render([]); source.focus(); });
document.querySelector('#processBtn').addEventListener('click', () => {
  const parsed = parseIptvList(source.value); render(parsed.entries);
  showToast(parsed.entries.length ? `${parsed.entries.length} dirección(es) organizada(s)` : 'No se encontraron direcciones con credenciales');
});
document.querySelector('#copyBtn').addEventListener('click', async () => { await navigator.clipboard.writeText(toCsv(currentEntries)); showToast('CSV copiado'); });
document.querySelector('#downloadBtn').addEventListener('click', () => {
  const blob = new Blob([`\uFEFF${toCsv(currentEntries)}`], { type: 'text/csv;charset=utf-8' });
  const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'lista-iptv.csv'; link.click(); URL.revokeObjectURL(link.href);
});

updateCount();
