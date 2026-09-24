import { initDb, query, tableRef } from './db.js';

// Served directly from the Pages deploy: at ~16 MB this is well under
// Cloudflare Pages' 25 MiB single-asset cap on the Free plan, so unlike
// some sibling projects (hhs-dab, usajobs_historical) this doesn't need an
// R2 bucket in front of it. Rebuild with `python3 build_web_data.py`
// whenever the HuggingFace dataset changes.
const PARQUET_URL = 'data/contracts.parquet';

const COLUMNS = [
  { label: 'Agency', field: 'agency', filterType: 'multiselect', index: 1 },
  { label: 'Award', field: 'text', filterType: 'text', index: 2 },
];

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// Same lightweight "no chart library" bar as hhs-dab's volume-by-year panel
// -- div heights scaled to the tallest year, nothing this static site
// doesn't already have.
async function renderVolumeByYear(conn, t) {
  const el = document.getElementById('volumeByYear');
  if (!el) return;
  const rows = await query(conn, `
    SELECT year, COUNT(*) AS n FROM ${t}
    WHERE year IS NOT NULL GROUP BY year ORDER BY year
  `);
  if (!rows.length) return;
  const max = Math.max(...rows.map((r) => Number(r.n)));
  el.innerHTML = `
    <h3>Awards by year</h3>
    <div class="year-bars">
      ${rows.map((r) => {
        const n = Number(r.n);
        const pct = Math.max(2, Math.round((n / max) * 100));
        return `<div class="year-bar" title="${r.year}: ${n.toLocaleString()}">
          <div class="year-bar-fill" style="height:${pct}%"></div>
          <div class="year-bar-label">${String(r.year).slice(2)}</div>
        </div>`;
      }).join('')}
    </div>
  `;
}

async function renderTopAgencies(conn, t) {
  const el = document.getElementById('topAgencies');
  if (!el) return;
  const rows = await query(conn, `
    SELECT agency, COUNT(*) AS n FROM ${t}
    WHERE agency IS NOT NULL GROUP BY agency ORDER BY n DESC LIMIT 8
  `);
  if (!rows.length) return;
  el.innerHTML = `
    <h3>Top agencies</h3>
    <ul class="outcome-list">
      ${rows.map((r) => `<li><span class="outcome-label">${escapeHtml(r.agency)}</span>
        <span class="outcome-count">${Number(r.n).toLocaleString()}</span></li>`).join('')}
    </ul>
  `;
}

async function main() {
  const conn = await initDb(PARQUET_URL);
  const t = tableRef(conn);

  const rows = await query(conn, `
    SELECT id, CAST(date AS VARCHAR) AS date, year, agency, text, link, article_title
    FROM ${t}
    ORDER BY date DESC NULLS LAST, id
  `);

  const tableData = rows.map((r) => [
    r.date || '',
    r.agency || '',
    escapeHtml(r.text),
    r.link
      ? `<a href="${escapeHtml(r.link)}" target="_blank" rel="noopener" title="${escapeHtml(r.article_title || '')}">Source &#8599;</a>`
      : '',
    r.year, // hidden, filter-only
  ]);

  const [stats] = await query(conn, `
    SELECT COUNT(*) AS total,
           COUNT(DISTINCT agency) AS agencies,
           COUNT(DISTINCT link) AS days,
           CAST(MIN(date) AS VARCHAR) AS min_date,
           CAST(MAX(date) AS VARCHAR) AS max_date
    FROM ${t}
  `);
  document.getElementById('statTotal').textContent = Number(stats.total).toLocaleString();
  document.getElementById('statAgencies').textContent = stats.agencies;
  document.getElementById('statDays').textContent = Number(stats.days).toLocaleString();
  document.getElementById('statDateRange').textContent =
    stats.min_date && stats.max_date ? `${stats.min_date} – ${stats.max_date}` : '–';

  await renderTopAgencies(conn, t);
  await renderVolumeByYear(conn, t);

  const YEAR_INDEX = 4;
  const allColumns = [
    ...COLUMNS,
    { label: 'Year', field: 'year', filterType: 'multiselect', index: YEAR_INDEX },
  ];

  const { table } = initDataTableWithFilters({
    tableSelector: '#contractsTable',
    filterBarId: 'filtersBar',
    tableOptions: {
      data: tableData,
      columns: [
        { data: 0 },
        { data: 1, className: 'award-agency' },
        { data: 2, className: 'award-text' },
        { data: 3, orderable: false },
        { data: 4, visible: false },
      ],
      order: [[0, 'desc']],
      pageLength: 25,
    },
    fieldTypes: Object.fromEntries(allColumns.map((c) => [c.field, c.filterType])),
    columns: allColumns,
    csvFilename: 'dod_daily_contracts.csv',
    csvColumns: [
      { header: 'Date', getData: (n, d) => d[0] },
      { header: 'Agency', getData: (n, d) => d[1] },
      { header: 'Award', getData: (n, d) => $('<div>').html(d[2]).text() },
      { header: 'Source', getData: (n, d) => $('<div>').html(d[3]).text() },
    ],
  });
  void table;
}

main().catch((err) => {
  console.error(err);
  showToast('Failed to load contracts', true);
});
