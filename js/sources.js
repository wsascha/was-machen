/**
 * Family Weekend Compass - Sources directory and performance statistics
 */

let sourcesCatalog = [];
let totalEventsCount = 0;
let activeSourceFilter = 'all';
let currentSort = 'perf'; // 'perf' | 'alpha' | 'has-events'

async function initSourcesPage() {
  try {
    const response = await fetch('data/sources.json');
    const data = await response.json();
    sourcesCatalog = data.sources || data.evaluated_sources_catalog || [];
    totalEventsCount = (data.metadata && data.metadata.total_events !== undefined)
      ? data.metadata.total_events
      : (data.events || []).length;

    updateHeaderMetrics(data);
    renderSources();

    const searchInput = document.getElementById('sources-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', () => renderSources());
    }

    const filterBtns = document.querySelectorAll('.source-filter-btn');
    filterBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        activeSourceFilter = btn.dataset.sourceFilter || 'all';
        filterBtns.forEach((b) => b.setAttribute('aria-pressed', 'false'));
        btn.setAttribute('aria-pressed', 'true');
        renderSources();
      });
    });

    const sortBtns = document.querySelectorAll('.source-sort-btn');
    sortBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        currentSort = btn.dataset.sort || 'perf';
        sortBtns.forEach((b) => b.setAttribute('aria-pressed', 'false'));
        btn.setAttribute('aria-pressed', 'true');
        renderSources();
      });
    });

    initBackToTop();
  } catch (err) {
    console.error('Failed to load sources catalog:', err);
  }
}

function updateHeaderMetrics(data) {
  const totalSources = sourcesCatalog.length;
  const activeSources = sourcesCatalog.filter((s) => (s.events_count || 0) > 0).length;

  const countDisplay = document.getElementById('sources-count-display');
  if (countDisplay) countDisplay.textContent = totalSources;

  const statTotalSources = document.getElementById('stat-total-sources');
  if (statTotalSources) statTotalSources.textContent = totalSources;

  const statActiveSources = document.getElementById('stat-active-sources');
  if (statActiveSources) statActiveSources.textContent = activeSources;

  const statTotalEvents = document.getElementById('stat-total-events');
  if (statTotalEvents) statTotalEvents.textContent = totalEventsCount;
}

function renderSources() {
  const gridEl = document.getElementById('sources-directory-grid');
  const statsBoxEl = document.getElementById('sources-stats-box');
  const searchInput = document.getElementById('sources-search-input');
  if (!gridEl) return;

  const query = (searchInput ? searchInput.value : '').trim().toLowerCase();

  let filtered = sourcesCatalog.filter((src) => {
    if (activeSourceFilter !== 'all' && src.type !== activeSourceFilter) {
      return false;
    }
    if (currentSort === 'has-events' && (src.events_count || 0) === 0) {
      return false;
    }
    if (query) {
      const haystack = [
        src.name,
        src.region,
        src.type_label || '',
        src.description || '',
        ...(src.selected_events || []).map((e) => e.title)
      ]
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });

  // Apply Sorting
  filtered.sort((a, b) => {
    if (currentSort === 'perf' || currentSort === 'has-events') {
      const countDiff = (b.events_count || 0) - (a.events_count || 0);
      if (countDiff !== 0) return countDiff;
      return a.name.localeCompare(b.name, 'de');
    }
    // Alphabetical
    return a.name.localeCompare(b.name, 'de');
  });

  if (statsBoxEl) {
    statsBoxEl.innerHTML = `
      <strong>${filtered.length}${filtered.length !== sourcesCatalog.length ? ` / ${sourcesCatalog.length}` : ''}</strong>
      <span>Aktive Quellen</span>
    `;
  }

  if (filtered.length === 0) {
    gridEl.innerHTML = `
      <li style="grid-column: 1 / -1; padding: 2.5rem 1.5rem; background: var(--bg-surface); border-radius: var(--radius-md); border: 1px dashed var(--border-strong); text-align: center; color: var(--text-secondary);">
        <p style="margin: 0 0 0.5rem; font-size: 1.05rem; font-weight: 700;">Keine Quellen gefunden</p>
        <p style="margin: 0; font-size: 0.88rem;">Passe die Suchbegriffe oder die Filter-Auswahl oben an.</p>
      </li>
    `;
    return;
  }

  gridEl.innerHTML = filtered
    .map((src) => {
      const flag = src.country === 'FR' ? '🇫🇷' : '🇩🇪';
      const typeIcon = src.type_icon || '📚';
      const typeLabel = src.type_label || 'Regionale Quelle';
      const eventCount = src.events_count || 0;

      let perfBadgeHtml = '';
      if (eventCount > 0) {
        perfBadgeHtml = `<span class="source-perf-badge perf-active">${eventCount} ${eventCount === 1 ? 'Event' : 'Events'} ausgewählt</span>`;
      } else {
        perfBadgeHtml = `<span class="source-perf-badge perf-idle">0 Events ausgewählt</span>`;
      }

      const descHtml = src.description
        ? `<p class="source-card-desc">${src.description}</p>`
        : '';

      let selectedEventsHtml = '';
      if (eventCount > 0 && Array.isArray(src.selected_events) && src.selected_events.length > 0) {
        const listItems = src.selected_events
          .map((e) => `<li><strong>${e.title}</strong></li>`)
          .join('');
        selectedEventsHtml = `
          <div class="source-selected-events">
            <div class="source-selected-events-title">
              <span aria-hidden="true">🎯</span>
              <span>Für das Wochenende ausgewählt (${eventCount}):</span>
            </div>
            <ul class="source-selected-events-list">
              ${listItems}
            </ul>
          </div>
        `;
      }

      const displayUrl = src.url
        .replace(/^https?:\/\/(www\.)?/, '')
        .replace(/\/$/, '');

      return `
        <li class="source-directory-card">
          <div>
            <div class="source-card-top">
              <span class="source-type-pill"><span aria-hidden="true">${typeIcon}</span> ${typeLabel}</span>
              <span class="source-region-pill">${flag} ${src.region}</span>
            </div>
            <h3 class="source-card-name">${src.name}</h3>
            <div>${perfBadgeHtml}</div>
            ${descHtml}
            ${selectedEventsHtml}
          </div>
          <a href="${src.url}" target="_blank" rel="noopener noreferrer" class="source-card-link">
            <span>Zur Quelle: ${displayUrl}</span>
            <span aria-hidden="true">↗</span>
          </a>
        </li>
      `;
    })
    .join('');
}

/**
 * Initializes floating "Back to top" button with IntersectionObserver
 * and accessible smooth-scrolling behavior.
 */
function initBackToTop() {
  const btn = document.getElementById('btn-back-to-top');
  if (!btn) return;

  const sentinel = document.getElementById('scroll-sentinel');
  const toggleVisibility = (show) => {
    btn.classList.toggle('visible', show);
    btn.setAttribute('tabindex', show ? '0' : '-1');
  };

  if ('IntersectionObserver' in window && sentinel) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          // When sentinel is out of view, the user has scrolled down
          toggleVisibility(!entry.isIntersecting);
        });
      },
      { threshold: 0 }
    );
    observer.observe(sentinel);
  } else {
    // Fallback scroll listener
    window.addEventListener(
      'scroll',
      () => {
        toggleVisibility(window.scrollY > 250);
      },
      { passive: true }
    );
  }

  btn.addEventListener('click', () => {
    const prefersReducedMotion =
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({
      top: 0,
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
    });
  });
}

document.addEventListener('DOMContentLoaded', initSourcesPage);
