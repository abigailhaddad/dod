/**
 * shared-ui — DataTables filtering, CSV export, expandable rows.
 * Requires: jQuery, Bootstrap 5.3, DataTables.
 */

// ============================================
// Utilities
// ============================================

function getCleanURL() {
    const url = new URL(window.location);
    if (url.pathname.endsWith('/index.html'))
        url.pathname = url.pathname.replace(/\/index\.html$/, '/');
    return url;
}

function escapeHtml(text) {
    if (!text) return '';
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text).replace(/[&<>"']/g, m => map[m]);
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function highlightPhrases(text, phrases) {
    if (!text || !phrases || phrases.length === 0) return escapeHtml(text);
    let highlighted = escapeHtml(text);
    [...phrases].sort((a, b) => b.length - a.length).forEach(phrase => {
        const esc = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        highlighted = highlighted.replace(new RegExp(`\\b${esc}\\b|${esc}`, 'gi'),
            match => `<span class="highlight">${match}</span>`);
    });
    return highlighted;
}

// ============================================
// Bootstrap Modal wrapper
// ============================================

function createModal(options = {}) {
    const sizeClass = options.size ? `modal-${options.size}` : '';
    const centeredClass = options.centered !== false ? 'modal-dialog-centered' : '';

    const modal = document.createElement('div');
    modal.className = `modal fade ${options.className || ''}`;
    modal.setAttribute('tabindex', '-1');
    modal.setAttribute('aria-hidden', 'true');

    const dialogDiv = document.createElement('div');
    dialogDiv.className = `modal-dialog ${sizeClass} ${centeredClass}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'modal-content';

    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'modal-body';
    if (options.content) bodyDiv.innerHTML = options.content;

    contentDiv.appendChild(bodyDiv);
    dialogDiv.appendChild(contentDiv);
    modal.appendChild(dialogDiv);
    document.body.appendChild(modal);

    const bsModal = new bootstrap.Modal(modal, { backdrop: true, keyboard: true });
    modal._bsModal = bsModal;

    if (options.onClose) modal.addEventListener('hidden.bs.modal', options.onClose);
    modal.addEventListener('hidden.bs.modal', () => modal.remove());
    bsModal.show();

    return modal;
}

function closeModal(modal) {
    if (modal && modal._bsModal) modal._bsModal.hide();
    else if (modal && modal.parentNode) modal.remove();
}

// ============================================
// Toast (Bootstrap's toast requires more setup;
// this simpler version is more convenient)
// ============================================

function showToast(message, isError = false) {
    const toast = document.createElement('div');
    toast.className = 'sui-toast' + (isError ? ' sui-toast-error' : ' sui-toast-success');
    toast.textContent = message;
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 2000);
}

// ============================================
// Multiselect helpers (used by ColumnFilterManager)
// ============================================

function buildMultiselectOptionsHtml(sortedValues, options = {}) {
    const { selectedValues = [], maxHeight = '300px', itemStyle = '', scrollHint = false,
            searchThreshold = 8, counts = null } = options;
    const labelStyle = itemStyle ? ` style="${itemStyle}"` : '';
    // A search box above two checkboxes (e.g. a Tribunal filter with just
    // "ALJ" and "Appellate Division") is more UI than the list needs -- it
    // earns its place on a long option list, not on every multiselect dialog.
    const searchBox = sortedValues.length > searchThreshold
        ? '<input type="text" class="form-control form-control-sm filter-options-search mb-2" placeholder="Search options...">'
        : '';
    return `
        ${searchBox}
        <div class="filter-options" style="max-height: ${maxHeight}; overflow-y: auto;">
            ${sortedValues.map(val => `
                <label class="filter-option d-flex align-items-center gap-2 px-2 py-1 rounded"${labelStyle}>
                    <input type="checkbox" value="${escapeHtml(val)}" ${selectedValues.includes(val) ? 'checked' : ''} class="form-check-input m-0">
                    <span class="flex-grow-1">${escapeHtml(val)}</span>
                    ${counts ? `<span class="filter-option-count text-muted small">${(counts.get(val) ?? 0).toLocaleString()}</span>` : ''}
                </label>
            `).join('')}
        </div>
        ${scrollHint ? '<div class="text-center text-muted small py-1">↓ Scroll for more</div>' : ''}
    `;
}

function wireMultiselectSearch(popover, focus = true) {
    const searchInput = popover.querySelector('.filter-options-search');
    if (!searchInput) return;
    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase();
        popover.querySelectorAll('.filter-option').forEach(el => {
            el.style.display = el.textContent.toLowerCase().includes(query) ? '' : 'none';
        });
    });
    if (focus) searchInput.focus();
}

// ============================================
// ColumnFilterManager
// ============================================

/**
 * Per-column filtering for DataTables: multiselect, text, and range dialogs.
 * Syncs filter state to URL query params for shareable links.
 *
 * Usage:
 *   const fm = new ColumnFilterManager({
 *     tableSelector: '#myTable',
 *     columns: [
 *       { index: 0, name: 'Status', type: 'multiselect' },
 *       { index: 1, name: 'Name',   type: 'text' },
 *       { index: 2, name: 'Count',  type: 'range' },
 *     ],
 *     filterBarId: 'filtersBar',
 *   });
 *   fm.init(dataTableInstance);
 */
class ColumnFilterManager {
    constructor(options) {
        this.tableSelector = options.tableSelector;
        this.columns = options.columns || [];
        this.filterBarId = options.filterBarId || null;
        this.syncURL = options.syncURL !== false;
        this.showCopyLinkButton = options.showCopyLinkButton !== false;
        this.table = null;
        this.activeFilters = {};
    }

    init(dataTable) {
        this.table = dataTable;
        this._setupRangeFilterSearch();
        if (this.filterBarId) this._setupFilterBar();
        if (this.syncURL) this._applyFiltersFromURL();
    }

    _setupRangeFilterSearch() {
        const self = this;
        $.fn.dataTable.ext.search.push(function(settings, data) {
            if (settings.nTable !== self.table.table().node()) return true;
            for (const colIndex in self.activeFilters) {
                const filter = self.activeFilters[colIndex];
                if (filter.type === 'range') {
                    const val = parseFloat(data[parseInt(colIndex)].replace(/,/g, ''));
                    if (isNaN(val)) return false;
                    if (filter.min !== null && val < filter.min) return false;
                    if (filter.max !== null && val > filter.max) return false;
                }
            }
            return true;
        });
    }

    _setupFilterBar() {
        const filterBar = document.getElementById(this.filterBarId);
        if (!filterBar) return;

        const buttonContainer = document.getElementById('toolbarButtons') || filterBar;

        let addBtn = buttonContainer.querySelector('.sui-add-filter-btn');
        if (!addBtn) {
            addBtn = document.createElement('button');
            addBtn.className = 'btn btn-sm btn-secondary sui-add-filter-btn';
            addBtn.textContent = '+ Add Filter';
            buttonContainer.appendChild(addBtn);
        }
        addBtn.addEventListener('click', () => this._openFilterSelection());

        if (this.syncURL && this.showCopyLinkButton) {
            let copyBtn = buttonContainer.querySelector('.sui-copy-link-btn');
            if (!copyBtn) {
                copyBtn = document.createElement('button');
                copyBtn.className = 'btn btn-sm btn-outline-secondary sui-copy-link-btn';
                copyBtn.textContent = '🔗 Copy Link';
                buttonContainer.appendChild(copyBtn);
                copyBtn.addEventListener('click', () => this.copyShareableURL());
            }
        }
    }

    _openFilterSelection() {
        const content = `
            <div class="filter-popover">
                <div class="filter-title">Add Filter</div>
                <div class="filter-options" style="max-height: 400px;">
                    ${this.columns.map(col => `
                        <label class="filter-option d-flex align-items-center gap-2 px-2 py-1 rounded">
                            <input type="checkbox" value="${col.index}" data-name="${escapeHtml(col.name)}" data-type="${col.type}" class="form-check-input m-0">
                            ${escapeHtml(col.name)}
                        </label>
                    `).join('')}
                </div>
            </div>
        `;
        const modal = createModal({ content });
        modal.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) {
                    closeModal(modal);
                    const col = this.columns.find(c => c.index === parseInt(checkbox.value));
                    if (col) this._openFilterDialog(col, col.index);
                }
            });
        });
    }

    _openFilterDialog(col, colIndex) {
        if (col.type === 'multiselect') this._openMultiselectDialog(col, colIndex);
        else if (col.type === 'range') this._openRangeDialog(col, colIndex);
        else if (col.type === 'fulltext') this._openFulltextDialog(col, colIndex);
        else this._openTextDialog(col, colIndex);
    }

    _openMultiselectDialog(col, colIndex) {
        const self = this;
        // A count per row containing the value, not per occurrence -- a row
        // whose "Judges" cell lists the same judge twice (it shouldn't, but
        // nothing guarantees it) would otherwise inflate that judge's count
        // past the table's own row total.
        const counts = new Map();
        this.table.column(colIndex).data().each(function(val) {
            const text = $('<div>').html(val).text().trim();
            if (text && text.includes(' | ')) {
                new Set(text.split(' | ').map(item => item.trim())).forEach(trimmed => {
                    if (trimmed && trimmed !== '—') counts.set(trimmed, (counts.get(trimmed) || 0) + 1);
                });
            } else if (text && text !== '—') {
                counts.set(text, (counts.get(text) || 0) + 1);
            }
        });

        const sortedValues = Array.from(counts.keys()).sort(col.sortFn || undefined);
        const selectedValues = (this.activeFilters[colIndex] || {}).values || [];

        const content = `
            <div class="filter-popover">
                <div class="filter-title">Filter: ${escapeHtml(col.name)}</div>
                ${buildMultiselectOptionsHtml(sortedValues, { selectedValues, scrollHint: true, counts })}
                <div class="d-flex gap-2 justify-content-end mt-3">
                    <button class="btn btn-sm btn-outline-secondary btn-filter-clear">Clear</button>
                    <button class="btn btn-sm btn-primary btn-filter-apply">Apply</button>
                </div>
            </div>
        `;

        const modal = createModal({ content });
        const $popover = $(modal).find('.filter-popover');
        wireMultiselectSearch($popover[0]);

        const optionsEl = $popover.find('.filter-options')[0];
        const hintEl = $popover.find('.text-center')[0];
        if (optionsEl && hintEl) {
            modal.addEventListener('shown.bs.modal', () => {
                if (optionsEl.scrollHeight <= optionsEl.clientHeight) hintEl.style.display = 'none';
            });
            optionsEl.addEventListener('scroll', () => {
                hintEl.style.display = (optionsEl.scrollTop + optionsEl.clientHeight >= optionsEl.scrollHeight - 2) ? 'none' : '';
            });
        }

        $popover.find('.btn-filter-clear').on('click', () => {
            delete self.activeFilters[colIndex];
            self.table.column(colIndex).search('').draw();
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });

        $popover.find('.btn-filter-apply').on('click', () => {
            const checked = [];
            $popover.find('input[type="checkbox"]:checked').each(function() { checked.push($(this).val()); });
            if (checked.length > 0) {
                self.activeFilters[colIndex] = { type: 'multiselect', values: checked, name: col.name };
                self.table.column(colIndex).search(checked.map(v => escapeRegex(v)).join('|'), true, false, true).draw();
            } else {
                delete self.activeFilters[colIndex];
                self.table.column(colIndex).search('').draw();
            }
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });
    }

    _openTextDialog(col, colIndex) {
        const self = this;
        const currentValue = (this.activeFilters[colIndex] || {}).value || '';

        const content = `
            <div class="filter-popover">
                <div class="filter-title">Filter: ${escapeHtml(col.name)}</div>
                <input type="text" class="form-control form-control-sm filter-text-input mb-1" placeholder="Enter search term..." value="${escapeHtml(currentValue)}">
                <div class="d-flex gap-2 justify-content-end mt-3">
                    <button class="btn btn-sm btn-outline-secondary btn-filter-clear">Clear</button>
                    <button class="btn btn-sm btn-primary btn-filter-apply">Apply</button>
                </div>
            </div>
        `;

        const modal = createModal({ content });
        const $popover = $(modal).find('.filter-popover');
        const $input = $popover.find('.filter-text-input');
        $input.focus();
        $input.on('keypress', e => { if (e.key === 'Enter') $popover.find('.btn-filter-apply').click(); });

        $popover.find('.btn-filter-clear').on('click', () => {
            delete self.activeFilters[colIndex];
            self.table.column(colIndex).search('').draw();
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });

        $popover.find('.btn-filter-apply').on('click', () => {
            const value = $input.val().trim();
            if (value) {
                self.activeFilters[colIndex] = { type: 'text', value, name: col.name };
                self.table.column(colIndex).search(value).draw();
            } else {
                delete self.activeFilters[colIndex];
                self.table.column(colIndex).search('').draw();
            }
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });
    }

    /**
     * Same dialog as a plain text filter, but for a column with no real
     * DataTable data to run a synchronous substring search against -- full
     * text living in an in-memory DuckDB table, say. `col.onApply(value)` is
     * awaited and does the actual matching (e.g. running a query and driving
     * a custom $.fn.dataTable.ext.search predicate); this method only owns
     * the popover, the filter chip, and URL sync, same as every other type.
     */
    _openFulltextDialog(col, colIndex) {
        const self = this;
        const currentValue = (this.activeFilters[colIndex] || {}).value || '';

        const content = `
            <div class="filter-popover">
                <div class="filter-title">Filter: ${escapeHtml(col.name)}</div>
                <input type="text" class="form-control form-control-sm filter-text-input mb-1" placeholder="Enter search term..." value="${escapeHtml(currentValue)}">
                <div class="d-flex gap-2 justify-content-end mt-3">
                    <button class="btn btn-sm btn-outline-secondary btn-filter-clear">Clear</button>
                    <button class="btn btn-sm btn-primary btn-filter-apply">Apply</button>
                </div>
            </div>
        `;

        const modal = createModal({ content });
        const $popover = $(modal).find('.filter-popover');
        const $input = $popover.find('.filter-text-input');
        $input.focus();
        $input.on('keypress', e => { if (e.key === 'Enter') $popover.find('.btn-filter-apply').click(); });

        $popover.find('.btn-filter-clear').on('click', async () => {
            delete self.activeFilters[colIndex];
            await col.onApply('');
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });

        $popover.find('.btn-filter-apply').on('click', async () => {
            const value = $input.val().trim();
            if (value) self.activeFilters[colIndex] = { type: 'fulltext', value, name: col.name };
            else delete self.activeFilters[colIndex];
            await col.onApply(value);
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });
    }

    _openRangeDialog(col, colIndex) {
        const self = this;
        const cur = this.activeFilters[colIndex] || {};

        const content = `
            <div class="filter-popover">
                <div class="filter-title">Filter: ${escapeHtml(col.name)}</div>
                <div class="mb-2">
                    <label class="form-label small">Minimum</label>
                    <input type="number" class="form-control form-control-sm filter-range-min" value="${escapeHtml(cur.min || '')}">
                </div>
                <div class="mb-2">
                    <label class="form-label small">Maximum</label>
                    <input type="number" class="form-control form-control-sm filter-range-max" value="${escapeHtml(cur.max || '')}">
                </div>
                <div class="d-flex gap-2 justify-content-end mt-3">
                    <button class="btn btn-sm btn-outline-secondary btn-filter-clear">Clear</button>
                    <button class="btn btn-sm btn-primary btn-filter-apply">Apply</button>
                </div>
            </div>
        `;

        const modal = createModal({ content });
        const $popover = $(modal).find('.filter-popover');
        $popover.find('.filter-range-min').focus();

        $popover.find('.btn-filter-clear').on('click', () => {
            delete self.activeFilters[colIndex];
            self.table.draw();
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });

        $popover.find('.btn-filter-apply').on('click', () => {
            const minVal = $popover.find('.filter-range-min').val().trim();
            const maxVal = $popover.find('.filter-range-max').val().trim();
            if (minVal || maxVal) {
                self.activeFilters[colIndex] = {
                    type: 'range',
                    min: minVal ? parseFloat(minVal) : null,
                    max: maxVal ? parseFloat(maxVal) : null,
                    name: col.name
                };
                self.table.draw();
            } else {
                delete self.activeFilters[colIndex];
                self.table.draw();
            }
            self._updateFilterBar();
            if (self.syncURL) self._updateURL();
            closeModal(modal);
        });
    }

    _updateFilterBar() {
        if (!this.filterBarId) return;
        const filterBar = document.getElementById(this.filterBarId);
        if (!filterBar) return;

        filterBar.querySelectorAll('.filter-chip.column-filter-chip').forEach(c => c.remove());
        const existingLabel = filterBar.querySelector('.bar-label.filter-label');
        if (existingLabel) existingLabel.remove();

        const hasFilters = Object.keys(this.activeFilters).length > 0;
        const hasSearchChip = filterBar.querySelector('#search-chip') !== null;

        // The empty-state span is static markup the page ships with, not
        // something this class ever created -- so unlike the label and
        // chips above, it has to be toggled rather than always removed and
        // conditionally rebuilt, or it sits there next to real chips.
        const emptyState = filterBar.querySelector('.filters-bar-empty');
        if (emptyState) emptyState.style.display = (hasFilters || hasSearchChip) ? 'none' : '';

        if (hasFilters || hasSearchChip) {
            const label = document.createElement('span');
            label.className = 'bar-label filter-label';
            label.textContent = 'Filtered by:';
            filterBar.insertBefore(label, filterBar.firstChild);

            Object.entries(this.activeFilters).forEach(([colIndex, filter]) => {
                const chip = document.createElement('div');
                chip.className = 'filter-chip column-filter-chip';

                let displayValue;
                if (filter.type === 'multiselect') {
                    displayValue = filter.values.join(', ');
                } else if (filter.type === 'range') {
                    const parts = [];
                    if (filter.min !== null) parts.push(`≥ ${filter.min.toLocaleString()}`);
                    if (filter.max !== null) parts.push(`≤ ${filter.max.toLocaleString()}`);
                    displayValue = parts.join(' and ');
                } else {
                    displayValue = filter.value;
                }

                chip.innerHTML = `
                    <span class="filter-chip-label">${escapeHtml(filter.name)}:</span>
                    <span class="filter-chip-value">${escapeHtml(displayValue)}</span>
                    <span class="filter-chip-remove">&times;</span>
                `;
                chip.querySelector('.filter-chip-remove').addEventListener('click', () => {
                    delete this.activeFilters[colIndex];
                    if (filter.type === 'fulltext') {
                        const col = this.columns.find(c => c.index === parseInt(colIndex));
                        if (col?.onApply) col.onApply('');
                        this.table.draw();
                    } else {
                        this.table.column(parseInt(colIndex)).search('').draw();
                    }
                    this._updateFilterBar();
                    if (this.syncURL) this._updateURL();
                });
                filterBar.appendChild(chip);
            });
        }
    }

    clearAll() {
        Object.entries(this.activeFilters).forEach(([colIndex, filter]) => {
            if (filter.type === 'fulltext') {
                const col = this.columns.find(c => c.index === parseInt(colIndex));
                if (col?.onApply) col.onApply('');
            } else {
                this.table.column(parseInt(colIndex)).search('');
            }
        });
        this.activeFilters = {};
        this._updateFilterBar();
        if (this.syncURL) this._updateURL();
        this.table.draw();
    }

    _saveToSession() {
        try {
            const key = 'columnFilters_' + this.tableSelector;
            if (Object.keys(this.activeFilters).length > 0)
                sessionStorage.setItem(key, JSON.stringify(this.activeFilters));
            else
                sessionStorage.removeItem(key);
        } catch (e) {}
    }

    _loadFromSession() {
        try {
            const key = 'columnFilters_' + this.tableSelector;
            const saved = sessionStorage.getItem(key);
            return saved ? JSON.parse(saved) : null;
        } catch (e) { return null; }
    }

    _updateURL() {
        const url = getCleanURL();
        const sortVal = url.searchParams.getAll('sort');
        url.search = '';
        if (sortVal.length) sortVal.forEach(v => url.searchParams.append('sort', v));

        Object.entries(this.activeFilters).forEach(([colIndex, filter]) => {
            const paramKey = filter.name.toLowerCase().replace(/[^a-z0-9]+/g, '_');
            if (filter.type === 'multiselect') url.searchParams.set(paramKey, filter.values.join(','));
            else if (filter.type === 'range') url.searchParams.set(paramKey, `${filter.min ?? ''}-${filter.max ?? ''}`);
            else url.searchParams.set(paramKey, filter.value);
        });

        window.history.replaceState({}, '', url);
        this._saveToSession();
    }

    _applyFiltersFromState(savedFilters) {
        Object.entries(savedFilters).forEach(([colIndex, filter]) => {
            const idx = parseInt(colIndex);
            this.activeFilters[idx] = filter;
            if (filter.type === 'multiselect')
                this.table.column(idx).search(filter.values.map(v => escapeRegex(v)).join('|'), true, false);
            else if (filter.type === 'fulltext') {
                // Async and column-less: fire it, don't block the rest of
                // this restore on a DB round trip the way every other type
                // doesn't need to.
                const col = this.columns.find(c => c.index === idx);
                if (col?.onApply) col.onApply(filter.value);
            } else if (filter.type !== 'range')
                this.table.column(idx).search(filter.value);
        });
        this._updateFilterBar();
        if (this.syncURL) this._updateURL();
        this.table.draw();
    }

    _applyFiltersFromURL() {
        const params = new URLSearchParams(window.location.search);
        const paramToColumn = {};
        this.columns.forEach(col => {
            paramToColumn[col.name.toLowerCase().replace(/[^a-z0-9]+/g, '_')] = col;
        });

        const hasColumnFilterParams = Array.from(params.keys()).some(k => paramToColumn[k]);
        if (!hasColumnFilterParams) {
            const saved = this._loadFromSession();
            if (saved && Object.keys(saved).length > 0) this._applyFiltersFromState(saved);
            return;
        }

        params.forEach((value, key) => {
            const col = paramToColumn[key];
            if (!col) return;
            if (col.type === 'multiselect') {
                const values = value.split(',').map(v => v.trim()).filter(v => v);
                if (values.length) {
                    this.activeFilters[col.index] = { type: 'multiselect', values, name: col.name };
                    this.table.column(col.index).search(values.map(v => escapeRegex(v)).join('|'), true, false);
                }
            } else if (col.type === 'range') {
                const parts = value.split('-');
                const min = parts[0] ? parseFloat(parts[0]) : null;
                const max = parts[1] ? parseFloat(parts[1]) : null;
                if (min !== null || max !== null)
                    this.activeFilters[col.index] = { type: 'range', min, max, name: col.name };
            } else if (col.type === 'fulltext') {
                if (value) {
                    this.activeFilters[col.index] = { type: 'fulltext', value, name: col.name };
                    if (col.onApply) col.onApply(value);
                }
            } else if (value) {
                this.activeFilters[col.index] = { type: 'text', value, name: col.name };
                this.table.column(col.index).search(value);
            }
        });

        this._updateFilterBar();
        this._saveToSession();
        this.table.draw();
    }

    copyShareableURL() {
        navigator.clipboard.writeText(window.location.href)
            .then(() => showToast('Link copied to clipboard!'))
            .catch(() => showToast('Failed to copy link', true));
    }
}

// ============================================
// Config helper
// ============================================

/**
 * Build ColumnFilterManager column config from a fieldTypes map.
 *
 * @param {Object} fieldTypes  { fieldName: 'multiselect'|'text'|'range' }
 * @param {Array}  columns     [{ field, label, index? }]
 * @returns {Array} config for ColumnFilterManager
 */
function buildColumnFilters(fieldTypes, columns) {
    const result = [];
    columns.forEach((col, i) => {
        const filterType = fieldTypes[col.field];
        if (filterType) {
            const entry = { index: col.index !== undefined ? col.index : i, name: col.label, type: filterType };
            if (col.sortFn) entry.sortFn = col.sortFn;
            if (col.onApply) entry.onApply = col.onApply;
            result.push(entry);
        }
    });
    return result;
}

// ============================================
// Filter bar factory
// ============================================

function ensureFilterBar(tableSelector, filterBarId) {
    if (document.getElementById(filterBarId)) return filterBarId;
    const table = document.querySelector(tableSelector);
    if (table) {
        const container = document.createElement('div');
        container.className = 'filters-bar-container';
        const bar = document.createElement('div');
        bar.className = 'filters-bar';
        bar.id = filterBarId;
        bar.innerHTML = `<span class="filters-bar-empty">No filters applied</span>`;
        container.appendChild(bar);
        table.parentNode.insertBefore(container, table);
    }
    return filterBarId;
}

/**
 * One-call DataTable + filter + CSV setup.
 *
 * @param {Object} options
 * @param {string}  options.tableSelector
 * @param {Object}  options.tableOptions    DataTable init options
 * @param {Object}  options.fieldTypes      { field: 'multiselect'|'text'|'range' }
 * @param {Array}   options.columns         [{ field, label, index? }]
 * @param {string}  options.filterBarId     optional; auto-generated if omitted
 * @param {boolean} options.csvDownload     default true
 * @param {string}  options.csvFilename
 * @param {Array}   options.csvColumns      [{ header, getData }]
 * @returns {{ table, filterManager }}
 */
function initDataTableWithFilters(options) {
    const { tableSelector, tableOptions, fieldTypes, columns,
            filterBarId, csvDownload = true, csvFilename = null, csvColumns = null } = options;

    const finalFilterBarId = filterBarId || 'filtersBar_' + Math.random().toString(36).substr(2, 9);
    ensureFilterBar(tableSelector, finalFilterBarId);

    if ($.fn.dataTable.isDataTable(tableSelector)) $(tableSelector).DataTable().destroy();
    const table = $(tableSelector).DataTable(tableOptions);

    const filterColumns = buildColumnFilters(fieldTypes, columns);
    const filterManager = new ColumnFilterManager({ tableSelector, columns: filterColumns, filterBarId: finalFilterBarId });
    filterManager.init(table);

    if (csvDownload) {
        const tableName = tableSelector.replace(/[#.]/g, '');
        const defaultFilename = `${tableName}_${new Date().toISOString().split('T')[0]}.csv`;
        const csvContainerId = document.getElementById('toolbarButtons') ? 'toolbarButtons' : finalFilterBarId;
        addCsvDownloadButton({ containerId: csvContainerId, table, filename: csvFilename || defaultFilename, columns: csvColumns });
    }

    return { table, filterManager };
}

// ============================================
// CSV export
// ============================================

function escapeCsvValue(val) {
    if (val === null || val === undefined) return '';
    const str = String(val);
    return (str.includes(',') || str.includes('"') || str.includes('\n'))
        ? '"' + str.replace(/"/g, '""') + '"'
        : str;
}

function downloadTableAsCSV(options) {
    const { table, filename: rawFilename = 'export', columns = null, filteredOnly = true } = options;

    let filename = rawFilename;
    const dateStr = new Date().toISOString().split('T')[0];
    if (!filename.includes(dateStr))
        filename = filename.endsWith('.csv') ? filename.replace('.csv', `_${dateStr}.csv`) : `${filename}_${dateStr}`;
    if (!filename.endsWith('.csv')) filename += '.csv';

    if (!table) return;
    const rows = table.rows(filteredOnly ? { search: 'applied' } : undefined).nodes();
    if (!rows.length) { showToast('No rows to export', true); return; }

    let headers = [], csvRows = [];

    if (columns) {
        headers = columns.map(col => col.header);
        Array.from(rows).forEach(rowNode => {
            const rowData = table.row(rowNode).data();
            csvRows.push(columns.map(col => escapeCsvValue(col.getData(rowNode, rowData))).join(','));
        });
    } else {
        $(table.table().header()).find('th').each(function() {
            const t = $(this).text().trim();
            if (t) headers.push(t);
        });
        Array.from(rows).forEach(rowNode => {
            const rowValues = [];
            $(rowNode).find('td').each(function() {
                let cellText = $(this).text().trim();
                const link = $(this).find('a');
                if (link.length && link.attr('href') && cellText === 'View') cellText = link.attr('href');
                rowValues.push(escapeCsvValue(cellText));
            });
            csvRows.push(rowValues.join(','));
        });
    }

    const blob = new Blob([[headers.join(','), ...csvRows].join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    window.URL.revokeObjectURL(url); a.remove();
    showToast(`Downloaded ${rows.length} rows`);
}

function addCsvDownloadButton(options) {
    const { containerId, table, filename, columns = null, buttonText = '⬇ Download CSV' } = options;
    const container = document.getElementById(containerId);
    if (!container) return null;
    if (container.querySelector('.sui-csv-btn')) return container.querySelector('.sui-csv-btn');
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-outline-secondary sui-csv-btn';
    btn.textContent = buttonText;
    btn.addEventListener('click', () => downloadTableAsCSV({ table, filename, columns }));
    container.appendChild(btn);
    return btn;
}

// ============================================
// Expandable DataTable rows
// ============================================

/**
 * Per-row data store, keyed by the <tr> DOM node.
 *
 * We used to JSON.stringify the full rowData/childData into data-* attributes
 * on every parent row up front — that serialized the entire dataset into the
 * DOM (and re-parsed it) just to show a paginated view. Instead we keep the
 * objects here and look them up by node reference. DataTables reuses the same
 * <tr> nodes across pagination, so the key stays valid for the row's lifetime.
 * A WeakMap lets rows GC naturally if the table is torn down.
 */
const _expandableRowData = new WeakMap();

/** Retrieve the { rowData, childData } stashed for an expandable parent row. */
function getExpandableRowData(node) {
    return _expandableRowData.get(node instanceof $ ? node[0] : node) || null;
}

/**
 * Set up expand/collapse for DataTable rows using row().child() API.
 *
 * @param {Object}   options
 * @param {string}   options.tableSelector
 * @param {Function} options.buildChildContent   (parsedData) => HTML string
 * @param {string}   options.childDataAttr       default: 'data-children'
 * @param {string}   options.childRowClass       default: 'child-doc-row'
 * @param {Function} options.onChildRowClick     optional callback(rowData)
 */
function setupDataTableExpandHandlers(options) {
    const { tableSelector, buildChildContent,
            childDataAttr = 'data-children',
            childRowClass = 'child-doc-row',
            onChildRowClick = null } = options;

    const table = $(tableSelector);
    const dt = table.DataTable();

    table.on('click', 'td.expand-control', function(e) {
        e.stopPropagation();
        const tr = $(this).closest('tr');
        const row = dt.row(tr);
        const expandIcon = tr.find('.expand-icon');

        if (row.child.isShown()) {
            row.child.hide();
            tr.removeClass('shown');
            expandIcon.removeClass('expanded');
        } else {
            // Prefer the JS-side store; fall back to the serialized attribute
            // for rows/sites that still set data-children directly.
            const stored = _expandableRowData.get(tr[0]);
            let childrenData = stored ? stored.childData : null;
            if (!childrenData) {
                const attr = tr.attr(childDataAttr);
                if (attr) { try { childrenData = JSON.parse(attr); } catch (e) { console.error('Error parsing children data:', e); } }
            }
            if (childrenData) {
                row.child(buildChildContent(childrenData)).show();
                tr.addClass('shown');
                expandIcon.addClass('expanded');
            }
        }
    });

    if (onChildRowClick && childRowClass) {
        table.on('click', '.' + childRowClass, function(e) {
            if (e.target.tagName === 'A') return;
            const dataAttr = $(this).attr('data-doc') || $(this).attr('data-row');
            if (dataAttr) {
                try { onChildRowClick(JSON.parse(dataAttr)); }
                catch (e) { console.error('Error parsing row data:', e); }
            }
        });
        table.on('mouseenter', '.' + childRowClass, function() { $(this).css('background', '#f0f4f8'); });
        table.on('mouseleave', '.' + childRowClass, function() { $(this).css('background', ''); });
    }
}

function createExpandableParentRow(options) {
    const { caseDisplayName, rowData, childData, cells } = options;
    const parentRow = document.createElement('tr');
    parentRow.className = 'parent-row';
    parentRow.setAttribute('data-case-name', caseDisplayName);
    // Stash the objects on the node instead of serializing them into attributes.
    // Retrieve with getExpandableRowData(tr); the expand handler reads childData
    // straight from here.
    if (rowData || childData) _expandableRowData.set(parentRow, { rowData, childData });

    const expandCell = document.createElement('td');
    expandCell.className = 'expand-control';
    const expandSpan = document.createElement('span');
    expandSpan.className = 'expand-icon';
    expandSpan.textContent = '▶';
    expandCell.appendChild(expandSpan);
    parentRow.appendChild(expandCell);

    cells.forEach(cellConfig => {
        const cell = document.createElement('td');
        if (typeof cellConfig === 'string') {
            cell.textContent = cellConfig;
        } else if (cellConfig.element) {
            cell.appendChild(cellConfig.element);
            if (cellConfig.style) cell.style.cssText = cellConfig.style;
        } else {
            cell.textContent = cellConfig.content || '';
            if (cellConfig.style) cell.style.cssText = cellConfig.style;
        }
        parentRow.appendChild(cell);
    });

    return parentRow;
}
