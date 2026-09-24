import { initDb, query, tableRef } from './db.js';

// Served directly from the Pages deploy: at ~16 MB this is well under
// Cloudflare Pages' 25 MiB single-asset cap on the Free plan, so unlike
// some sibling projects (hhs-dab, usajobs_historical) this doesn't need an
// R2 bucket in front of it. Rebuild with `python3 build_web_data.py`
// whenever the HuggingFace dataset changes.
const PARQUET_URL = 'data/contracts.parquet';

const COLUMNS = [
  { label: 'Agency', field: 'agency', filterType: 'multiselect', index: 1 },
  { label: 'Company', field: 'company', filterType: 'text', index: 2 },
  { label: 'Place', field: 'place', filterType: 'text', index: 3 },
  { label: 'Award', field: 'text', filterType: 'text', index: 4 },
];

// Hidden, filter-only column -- not rendered as a <th>, just along for the
// ride in each row's data array so the panels below can group by year
// without a second query.
const YEAR_INDEX = 6;

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function formatMonthYear(dateStr) {
  if (!dateStr) return '';
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

// The stat cards and the two panels all describe "the rows currently on
// screen", not "the whole dataset" -- so they're recomputed from the
// DataTable's own filtered row set (rows({search:'applied'}), the same API
// the table itself draws from) every time a filter changes, rather than
// queried from DuckDB once at load. That keeps them consistent with the
// table by construction: whatever the table is showing IS the aggregate.
function computeAggregates(table) {
  const rows = table.rows({ search: 'applied' }).data().toArray();
  const agencyCounts = new Map();
  const yearCounts = new Map();
  for (const r of rows) {
    const agency = r[1];
    const year = r[YEAR_INDEX];
    if (agency) agencyCounts.set(agency, (agencyCounts.get(agency) || 0) + 1);
    if (year) yearCounts.set(year, (yearCounts.get(year) || 0) + 1);
  }
  return { total: rows.length, agencyCounts, yearCounts };
}

function renderStats(agg) {
  document.getElementById('statTotal').textContent = agg.total.toLocaleString();
  document.getElementById('statAgencies').textContent = agg.agencyCounts.size;
}

function renderTopAgencies(agg) {
  const el = document.getElementById('topAgencies');
  if (!el) return;
  const top = Array.from(agg.agencyCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!top.length) {
    el.innerHTML = '<h3>Top agencies</h3><p class="text-muted small">No matching awards.</p>';
    return;
  }
  el.innerHTML = `
    <h3>Top agencies</h3>
    <ul class="outcome-list">
      ${top.map(([agency, n]) => `<li><span class="outcome-label">${escapeHtml(agency)}</span>
        <span class="outcome-count">${n.toLocaleString()}</span></li>`).join('')}
    </ul>
  `;
}

// Same lightweight "no chart library" bar as hhs-dab's volume-by-year panel
// -- div heights scaled to the tallest year, nothing this static site
// doesn't already have.
function renderVolumeByYear(agg) {
  const el = document.getElementById('volumeByYear');
  if (!el) return;
  const years = Array.from(agg.yearCounts.entries()).sort((a, b) => a[0] - b[0]);
  if (!years.length) {
    el.innerHTML = '<h3>Awards by year</h3><p class="text-muted small">No matching awards.</p>';
    return;
  }
  const max = Math.max(...years.map(([, n]) => n));
  el.innerHTML = `
    <h3>Awards by year</h3>
    <div class="year-bars">
      ${years.map(([year, n]) => {
        const pct = Math.max(2, Math.round((n / max) * 100));
        return `<div class="year-bar" title="${year}: ${n.toLocaleString()}">
          <div class="year-bar-fill" style="height:${pct}%"></div>
          <div class="year-bar-label">${String(year).slice(2)}</div>
        </div>`;
      }).join('')}
    </div>
  `;
}

function renderAggregates(table) {
  const agg = computeAggregates(table);
  renderStats(agg);
  renderTopAgencies(agg);
  renderVolumeByYear(agg);
}

async function main() {
  const conn = await initDb(PARQUET_URL);
  const t = tableRef(conn);

  const rows = await query(conn, `
    SELECT id, CAST(date AS VARCHAR) AS date, year, agency, company, place, text, link, article_title
    FROM ${t}
    ORDER BY date DESC NULLS LAST, id
  `);

  const tableData = rows.map((r) => [
    r.date || '',
    r.agency || '',
    r.company || '',
    r.place || '',
    escapeHtml(r.text),
    r.link
      ? `<a href="${escapeHtml(r.link)}" target="_blank" rel="noopener" title="${escapeHtml(r.article_title || '')}">Source &#8599;</a>`
      : '',
    r.year,
  ]);

  // The subtitle's date range describes the whole dataset, not whatever's
  // filtered, so it's set once here from every row rather than recomputed
  // alongside the aggregates below -- and computed from the data itself
  // (not hardcoded) so it keeps saying the right thing as new days get
  // scraped in.
  const subtitleEl = document.getElementById('siteSubtitle');
  const dates = rows.map((r) => r.date).filter(Boolean);
  if (subtitleEl && dates.length) {
    const minDate = dates.reduce((a, b) => (a < b ? a : b));
    const maxDate = dates.reduce((a, b) => (a > b ? a : b));
    subtitleEl.textContent =
      `Every contract award scraped from war.gov's daily press releases, ${formatMonthYear(minDate)}–${formatMonthYear(maxDate)}`;
  }

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
        { data: 2, className: 'award-agency' },
        { data: 3, className: 'award-agency' },
        { data: 4, className: 'award-text' },
        { data: 5, orderable: false },
        { data: 6, visible: false },
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
      { header: 'Company', getData: (n, d) => d[2] },
      { header: 'Place', getData: (n, d) => d[3] },
      { header: 'Award', getData: (n, d) => $('<div>').html(d[4]).text() },
      { header: 'Source', getData: (n, d) => $('<div>').html(d[5]).text() },
    ],
  });

  renderAggregates(table);
  table.on('draw', () => renderAggregates(table));
}

main().catch((err) => {
  console.error(err);
  showToast('Failed to load contracts', true);
});
