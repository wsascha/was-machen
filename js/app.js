/**
 * Was machen wir am Wochenende? (77815 Bühl + max. 60 Min. / 1 Std. Fahrzeit)
 * Client-side Interactive Map, Multi-Criteria Filter & Native Dialog Controller
 */

const COORDS = [48.6953, 8.1350];

const CATEGORY_META = {
  theater: {
    label: 'Theater, Musik & Bühne',
    icon: '🎭',
    color: '#7c3aed',
    badgeClass: 'badge-cat-theater'
  },
  museum: {
    label: 'Mitmach-Museum & Wissen',
    icon: '🔬',
    color: '#0284c7',
    badgeClass: 'badge-cat-museum'
  },
  market: {
    label: 'Markt, Lichter & Brauchtum',
    icon: '🏮',
    color: '#d97706',
    badgeClass: 'badge-cat-market'
  },
  creative: {
    label: 'Kreativ, Genuss & Handwerk',
    icon: '🎨',
    color: '#db2777',
    badgeClass: 'badge-cat-creative'
  },
  nature: {
    label: 'Natur, Tiere & Burg',
    icon: '🌲',
    color: '#15803d',
    badgeClass: 'badge-cat-nature'
  },
  action: {
    label: 'Freizeitpark & Action',
    icon: '🎢',
    color: '#dc2626',
    badgeClass: 'badge-cat-action'
  }
};

const WEATHER_META = {
  indoor: { label: '100% Indoor (Regensicher)', icon: '🏠' },
  mixed: { label: 'Indoor & Outdoor Kombi', icon: '🌤️' },
  outdoor: { label: 'Outdoor-Erlebnis', icon: '🌲' }
};

const CRITERIA_LABELS = {
  age_fit: { title: 'Alters-Eignung (4–9 J.)', icon: '👧🧒', short: 'Alter 4–9' },
  experience_value: { title: 'Erlebnis- & Mitmach-Faktor', icon: '✨', short: 'Mitmachen' },
  weather_suitability: { title: 'Wetter- & November-Eignung', icon: '☔', short: 'Wetterfest' },
  relaxation_parents: { title: 'Entspannungs-Faktor (Eltern)', icon: '🧘', short: 'Entspannt' },
  travel_parking: { title: 'Anfahrt & Parken', icon: '🚗', short: 'Anfahrt' },
  infrastructure_food: { title: 'Infrastruktur & Gastro', icon: '🥨', short: 'Gastro/WC' },
  language_accessibility: { title: 'Sprach-Komfort (DE/FR)', icon: '🗣️', short: 'Sprache' }
};

let allEvents = [];
let sourcesCatalog = [];
let activeSourceFilter = 'all';
let mapInstance = null;
let markersLayer = null;
let markerByEventId = new Map();
let activePresets = new Set();

/**
 * Mandatory Light-Dismiss Fallback per Modern Web Guidance (`light-dismiss-a-dialog`)
 */
function setupDialogLightDismissFallback() {
  if (!('closedBy' in HTMLDialogElement.prototype)) {
    const dialogs = document.querySelectorAll('dialog[closedby="any"]');
    dialogs.forEach((dialog) => {
      dialog.addEventListener('click', (event) => {
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const isDialogContent =
          rect.top <= event.clientY &&
          event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX &&
          event.clientX <= rect.left + rect.width;

        if (isDialogContent) return;
        dialog.close();
      });
    });
  }
}

/**
 * Initialize Leaflet Map centered on 77815 Bühl
 */
function initMap() {
  mapInstance = L.map('map', {
    center: COORDS,
    zoom: 9,
    scrollWheelZoom: true,
    zoomControl: false
  });

  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> Mitwirkende',
    maxZoom: 19
  }).addTo(mapInstance);

  markersLayer = L.layerGroup().addTo(mapInstance);
}

/**
 * Filter & Sort Events based on current UI controls
 */
function getFilteredEvents() {
  const dayFilter = document.getElementById('filter-day')?.value || 'all';
  const driveEl = document.getElementById('filter-drive');
  const maxDrive = driveEl ? parseInt(driveEl.value, 10) : 60;

  // Update slider output display
  const driveValOutput = document.getElementById('drive-val');
  if (driveValOutput) {
    driveValOutput.textContent = maxDrive >= 60 ? 'max. 60 Min.' : `max. ${maxDrive} Min.`;
  }

  let activeCount = 0;
  if (dayFilter !== 'all') activeCount++;
  if (maxDrive < 60) activeCount++;
  activeCount += activePresets.size;

  const isAnyFilterActive = activeCount > 0;
  const resetBtn = document.getElementById('btn-reset-filters');
  if (resetBtn) {
    resetBtn.hidden = false;
    resetBtn.innerHTML = '<span aria-hidden="true">↺</span> Reset';
    resetBtn.setAttribute(
      'title',
      isAnyFilterActive ? `${activeCount} aktive Filter zurücksetzen` : 'Alle Filter zurücksetzen'
    );
  }

  const filtered = allEvents.filter((ev) => {
    if (dayFilter !== 'all' && !(ev.days || []).includes(dayFilter)) {
      return false;
    }

    const driveMin = ev.drive_minutes ?? ev.drive_minutes_from_buehl ?? 0;
    if (driveMin > maxDrive) {
      return false;
    }

    // Quick Preset filters (combinable via logical AND)
    if (activePresets.has('bad-weather') && ev.weather_type !== 'indoor') {
      return false;
    }
    if (
      activePresets.has('hands-on') &&
      (ev.criteria_ratings?.experience_value?.score || 0) < 9.2
    ) {
      return false;
    }
    if (
      activePresets.has('calm') &&
      (ev.criteria_ratings?.relaxation_parents?.score || 0) < 8.5
    ) {
      return false;
    }

    return true;
  });

  filtered.sort((a, b) => {
    const driveA = a.drive_minutes ?? a.drive_minutes_from_buehl ?? 0;
    const driveB = b.drive_minutes ?? b.drive_minutes_from_buehl ?? 0;
    return b.family_score - a.family_score || driveA - driveB;
  });

  return filtered;
}

/**
 * Render Markers on the Leaflet Map
 */
function renderMapMarkers(events) {
  markersLayer.clearLayers();
  markerByEventId.clear();

  events.forEach((ev) => {
    const cat = CATEGORY_META[ev.category] || CATEGORY_META.museum;
    let titleSummary = ev.short_pin_label || ev.title;
    if (titleSummary.includes(' · ')) {
      titleSummary = titleSummary.split(' · ')[1];
    }

    const markerHtml = `
      <div class="marker-pin-wrap" data-event-id="${ev.id}" style="--marker-color: ${cat.color};" title="${ev.title} (${ev.city})">
        <div class="marker-bubble">
          <span class="marker-title">${titleSummary}</span>
          <span class="marker-score">${ev.family_score.toFixed(1)}</span>
        </div>
        <div class="marker-pointer"></div>
      </div>
    `;

    const icon = L.divIcon({
      className: 'custom-event-marker',
      html: markerHtml,
      iconSize: [110, 34],
      iconAnchor: [55, 33]
    });

    const marker = L.marker([ev.coordinates.lat, ev.coordinates.lon], { icon }).addTo(markersLayer);

    marker.on('click', () => {
      openEventDetailDialog(ev.id);
      highlightEventCard(ev.id, true);
    });

    markerByEventId.set(ev.id, marker);
  });
}

/**
 * Render Event Cards in the right-hand feed
 */
function renderEventsFeed(events) {
  const listEl = document.getElementById('events-list');
  const countEl = document.getElementById('feed-count');

  countEl.textContent = `${events.length} Events`;
  listEl.innerHTML = '';

  if (events.length === 0) {
    const emptyLi = document.createElement('li');
    emptyLi.className = 'event-card';
    emptyLi.innerHTML = `
      <h3 class="card-title">Keine Veranstaltungen für diese Filterkombination</h3>
      <p class="card-summary">Probiere einen größeren Fahrzeit-Radius (bis 60 Min.) oder setze die Schnellfilter zurück.</p>
    `;
    listEl.appendChild(emptyLi);
    return;
  }

  events.forEach((ev) => {
    const cat = CATEGORY_META[ev.category] || CATEGORY_META.museum;
    const weather = WEATHER_META[ev.weather_type] || WEATHER_META.indoor;
    const li = document.createElement('li');
    li.className = 'event-card';
    li.dataset.eventId = ev.id;

    const rAge = ev.criteria_ratings?.age_fit?.score || 9.0;
    const rExp = ev.criteria_ratings?.experience_value?.score || 9.0;
    const rWea = ev.criteria_ratings?.weather_suitability?.score || 8.5;
    const rRel = ev.criteria_ratings?.relaxation_parents?.score || 8.0;

    const sourcesHtml = (ev.sources || [])
      .map(
        (s) =>
          `<a href="${s.url}" target="_blank" rel="noopener noreferrer" class="source-tag">${s.name} ↗</a>`
      )
      .join('');

    li.innerHTML = `
      <div class="card-top-row">
        <div class="card-badges">
          <span class="badge ${cat.badgeClass}">
            <span aria-hidden="true">${cat.icon}</span> ${cat.label}
          </span>
          <span class="badge badge-weather">
            <span aria-hidden="true">${weather.icon}</span> ${weather.label}
          </span>
          <span class="badge badge-drive">
            <span aria-hidden="true">🚗</span> ${ev.drive_minutes ?? ev.drive_minutes_from_buehl} Min. (${ev.distance_km ?? ev.distance_km_from_buehl} km)
          </span>
          ${
            ev.country === 'FR'
              ? `<span class="badge badge-country-fr">🇫🇷 Elsass · ${ev.language_badge || 'Ohne Französisch machbar'}</span>`
              : ''
          }
        </div>

        <div class="family-score-box">
          <div class="score-pill">
            ${ev.family_score.toFixed(1)}<small>/10</small>
          </div>
          <span class="score-label">Familien-Score</span>
        </div>
      </div>

      <div>
        <h3 class="card-title">${ev.title}</h3>
      </div>

      <div class="card-meta-grid">
        <div class="meta-item">
          <span aria-hidden="true">📅</span>
          <span><strong>Wann:</strong> ${ev.date_display}</span>
        </div>
        <div class="meta-item">
          <span aria-hidden="true">📍</span>
          <span><strong>Wo:</strong> ${ev.venue_name}, ${ev.city}</span>
        </div>
        <div class="meta-item">
          <span aria-hidden="true">💶</span>
          <span><strong>Preis / Eintritt:</strong> ${ev.price_info || 'Siehe Details'}</span>
        </div>
        <div class="meta-item">
          <span aria-hidden="true">👧🧒</span>
          <span><strong>Alter:</strong> ${ev.age_suitability.label}</span>
        </div>
        <div class="meta-item">
          <span aria-hidden="true">⏱️</span>
          <span><strong>Dauer:</strong> ${ev.duration_display}</span>
        </div>
      </div>

      <p class="card-summary">${ev.summary}</p>

      <div class="criteria-mini-grid" aria-label="Kurzübersicht der Familien-Bewertungskriterien">
        <div class="mini-crit">
          <div class="mini-crit-header">
            <span>👧 Alter (4–9)</span>
            <span>${rAge.toFixed(1)}</span>
          </div>
          <div class="mini-bar-track">
            <div class="mini-bar-fill" style="--crit-score: ${rAge};"></div>
          </div>
        </div>
        <div class="mini-crit">
          <div class="mini-crit-header">
            <span>✨ Erlebnis</span>
            <span>${rExp.toFixed(1)}</span>
          </div>
          <div class="mini-bar-track">
            <div class="mini-bar-fill" style="--crit-score: ${rExp};"></div>
          </div>
        </div>
        <div class="mini-crit">
          <div class="mini-crit-header">
            <span>☔ Wetterfest</span>
            <span>${rWea.toFixed(1)}</span>
          </div>
          <div class="mini-bar-track">
            <div class="mini-bar-fill" style="--crit-score: ${rWea};"></div>
          </div>
        </div>
        <div class="mini-crit">
          <div class="mini-crit-header">
            <span>🧘 Entspannt</span>
            <span>${rRel.toFixed(1)}</span>
          </div>
          <div class="mini-bar-track">
            <div class="mini-bar-fill" style="--crit-score: ${rRel};"></div>
          </div>
        </div>
      </div>

      <div class="card-footer">
        <div class="sources-preview">
          <span>Quellen (${(ev.sources || []).length}):</span>
          ${sourcesHtml}
        </div>
        <div class="card-actions">
          <button type="button" class="btn-secondary btn-focus-map" data-event-id="${ev.id}">
            <span aria-hidden="true">🗺️</span> Auf Karte zeigen
          </button>
          <button type="button" class="btn-primary btn-open-details" data-event-id="${ev.id}">
            <span>Alle 7 Kriterien &amp; Details</span>
          </button>
        </div>
      </div>
    `;

    // Hover synchronization with map marker
    li.addEventListener('mouseenter', () => toggleMarkerHighlight(ev.id, true));
    li.addEventListener('mouseleave', () => toggleMarkerHighlight(ev.id, false));

    listEl.appendChild(li);
  });

  // Wire buttons via addEventListener (no inline onclick)
  listEl.querySelectorAll('.btn-focus-map').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.eventId;
      focusEventOnMap(id);
    });
  });

  listEl.querySelectorAll('.btn-open-details').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.eventId;
      openEventDetailDialog(id);
    });
  });
}

function toggleMarkerHighlight(eventId, isHighlighted) {
  const pinEl = document.querySelector(`.marker-pin-wrap[data-event-id="${eventId}"]`);
  if (pinEl) {
    pinEl.classList.toggle('is-highlighted', isHighlighted);
  }
}

function highlightEventCard(eventId, scrollIntoView = false) {
  document.querySelectorAll('.event-card').forEach((c) => c.classList.remove('is-active'));
  const card = document.querySelector(`.event-card[data-event-id="${eventId}"]`);
  if (card) {
    card.classList.add('is-active');
    if (scrollIntoView) {
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
}

function focusEventOnMap(eventId) {
  const ev = allEvents.find((item) => item.id === eventId);
  if (!ev || !mapInstance) return;
  mapInstance.flyTo([ev.coordinates.lat, ev.coordinates.lon], 13, { duration: 0.7 });
  highlightEventCard(eventId, false);
  toggleMarkerHighlight(eventId, true);
}

/**
 * Open the Native Modal Dialog (<dialog>) with the full 7-Criteria Family Evaluation
 */
function openEventDetailDialog(eventId) {
  const ev = allEvents.find((item) => item.id === eventId);
  if (!ev) return;

  const dialog = document.getElementById('event-dialog');
  const titleEl = document.getElementById('dialog-event-title');
  const badgesEl = document.getElementById('dialog-badges');
  const bodyEl = document.getElementById('dialog-event-body');

  const cat = CATEGORY_META[ev.category] || CATEGORY_META.museum;
  const weather = WEATHER_META[ev.weather_type] || WEATHER_META.indoor;

  titleEl.textContent = ev.title;
  badgesEl.innerHTML = `
    <span class="badge ${cat.badgeClass}">${cat.icon} ${cat.label}</span>
    <span class="badge badge-weather">${weather.icon} ${weather.label}</span>
    <span class="badge badge-drive">🚗 ${ev.drive_minutes ?? ev.drive_minutes_from_buehl} Min. (${ev.distance_km ?? ev.distance_km_from_buehl} km)</span>
    <span class="badge" style="background: var(--brand-primary); color: #fff;">⭐ Gesamt-Score: ${ev.family_score.toFixed(1)} / 10</span>
  `;

  const criteriaCardsHtml = Object.entries(CRITERIA_LABELS)
    .map(([key, meta]) => {
      const ratingObj = ev.criteria_ratings?.[key] || { score: 8.5, reason: '' };
      return `
        <div class="eval-card">
          <div class="eval-card-head">
            <span class="eval-card-title"><span aria-hidden="true">${meta.icon}</span> ${meta.title}</span>
            <span class="eval-card-score">${Number(ratingObj.score).toFixed(1)} / 10</span>
          </div>
          <div class="mini-bar-track" style="margin-bottom: 0.45rem;">
            <div class="mini-bar-fill" style="--crit-score: ${ratingObj.score};"></div>
          </div>
          <p class="eval-card-text">${ratingObj.reason}</p>
        </div>
      `;
    })
    .join('');

  const prosHtml = (ev.pros || []).map((p) => `<li>${p}</li>`).join('');
  const consHtml = (ev.tips_and_watchouts || []).map((c) => `<li>${c}</li>`).join('');
  const sourcesHtml = (ev.sources || [])
    .map(
      (s) =>
        `<li><a href="${s.url}" target="_blank" rel="noopener noreferrer" style="color: var(--brand-primary); font-weight: 600;">${s.name} (${s.url}) ↗</a></li>`
    )
    .join('');

  bodyEl.innerHTML = `
    <p style="margin: 0; font-size: 0.95rem; color: var(--text-secondary); line-height: 1.6;">
      ${ev.detailed_description || ev.summary}
    </p>

    <div class="card-meta-grid" style="font-size: 0.85rem;">
      <div class="meta-item">📅 <span><strong>Termine am Wochenende:</strong> ${ev.date_display}</span></div>
      <div class="meta-item">📍 <span><strong>Adresse:</strong> ${ev.address}</span></div>
      <div class="meta-item">💶 <span><strong>Eintritt / Preis:</strong> ${ev.price_info || 'Siehe Buchungsinfo'}</span></div>
      <div class="meta-item">🎟️ <span><strong>Tickets / Reservierung:</strong> ${ev.booking_info}</span></div>
      <div class="meta-item">🅿️ <span><strong>Parken:</strong> ${ev.parking_info}</span></div>
      <div class="meta-item">👧 <span><strong>Für 4–5 Jahre (Kita):</strong> ${ev.age_suitability.notes_4_5}</span></div>
      <div class="meta-item">🧒 <span><strong>Für 6–9 Jahre (Grundschule):</strong> ${ev.age_suitability.notes_6_9}</span></div>
    </div>

    <div>
      <h3 style="margin: 0 0 0.65rem; font-size: 1.05rem;">Detaillierte Familien-Bewertung nach 7 Kriterien</h3>
      <div class="evaluation-matrix">
        ${criteriaCardsHtml}
      </div>
    </div>

    <div class="pros-cons-grid">
      <div class="pro-box">
        <h4>✅ Warum sich der Ausflug lohnt</h4>
        <ul>${prosHtml}</ul>
      </div>
      <div class="con-box">
        <h4>💡 Eltern-Tipps &amp; Worauf ihr achten solltet</h4>
        <ul>${consHtml}</ul>
      </div>
    </div>

    <div style="background: var(--bg-page); padding: 0.9rem 1rem; border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
      <h4 style="margin: 0 0 0.4rem; font-size: 0.88rem;">📚 Verifizierte Quellen &amp; weiterführende Links</h4>
      <ul style="margin: 0; padding-left: 1.2rem; font-size: 0.83rem;">
        ${sourcesHtml}
      </ul>
    </div>
  `;

  dialog.showModal();
}

/**
 * Populate Methodology Sources in Dialog
 */
async function populateInfoDialogs() {
  if (sourcesCatalog.length === 0) {
    try {
      const resp = await fetch('data/sources.json');
      if (resp.ok) {
        const sdata = await resp.json();
        sourcesCatalog = sdata.sources || sdata.evaluated_sources_catalog || [];
      }
    } catch {
      // sources catalog is optional for main event view
    }
  }

  const sourcesListEl = document.getElementById('methodology-sources-list');
  if (sourcesListEl && sourcesCatalog.length > 0) {
    sourcesListEl.innerHTML = sourcesCatalog
      .map(
        (src) =>
          `<li style="margin-bottom: 0.3rem;"><a href="${src.url}" target="_blank" rel="noopener noreferrer" style="color: var(--brand-primary);">${src.name}</a> <small>(${src.region})</small></li>`
      )
      .join('');
  }

  const headerCountEl = document.getElementById('meta-sources-count');
  if (headerCountEl && sourcesCatalog.length > 0) {
    headerCountEl.textContent = `${sourcesCatalog.length} regionale Quellen`;
  }

  renderSourcesDirectory();
}

function renderSourcesDirectory() {
  const gridEl = document.getElementById('sources-directory-grid');
  const statsBoxEl = document.getElementById('sources-stats-box');
  if (!gridEl) return;

  const filteredSources = sourcesCatalog.filter((src) => {
    if (activeSourceFilter === 'all') return true;
    if (activeSourceFilter === 'FR') return src.country === 'FR';
    return src.type === activeSourceFilter;
  });

  if (statsBoxEl) {
    statsBoxEl.innerHTML = `
      <strong>${filteredSources.length}${activeSourceFilter !== 'all' ? ` / ${sourcesCatalog.length}` : ''}</strong>
      <span>Aktive Quellen</span>
    `;
  }

  gridEl.innerHTML = filteredSources
    .map((src) => {
      const flag = src.country === 'FR' ? '🇫🇷' : '🇩🇪';
      const typeIcon = src.type_icon || '📚';
      const typeLabel = src.type_label || 'Regionale Quelle';
      const descHtml = src.description
        ? `<p class="source-card-desc">${src.description}</p>`
        : '';

      return `
        <li class="source-directory-card">
          <div>
            <div class="source-card-top">
              <span class="source-type-pill"><span aria-hidden="true">${typeIcon}</span> ${typeLabel}</span>
              <span class="source-region-pill">${flag} ${src.region}</span>
            </div>
            <h3 class="source-card-name">${src.name}</h3>
            ${descHtml}
          </div>
          <a href="${src.url}" target="_blank" rel="noopener noreferrer" class="source-card-link">
            <span>Zur Quelle: ${src.url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</span>
            <span aria-hidden="true">↗</span>
          </a>
        </li>
      `;
    })
    .join('');
}

function fitMapToFilteredEvents(events) {
  if (!mapInstance) return;
  if (!events || events.length === 0) {
    mapInstance.flyTo(COORDS, 10, { duration: 0.45 });
    return;
  }
  const latLngs = events.map((e) => [e.coordinates.lat, e.coordinates.lon]);
  const bounds = L.latLngBounds(latLngs);
  mapInstance.flyToBounds(bounds, {
    paddingTopLeft: [50, 45],
    paddingBottomRight: [50, 75],
    maxZoom: 13,
    duration: 0.45
  });
}

function updateUI(shouldFitMap = true) {
  const filtered = getFilteredEvents();
  renderMapMarkers(filtered);
  renderEventsFeed(filtered);
  if (shouldFitMap) {
    fitMapToFilteredEvents(filtered);
  }
}

/**
 * Synchronize sticky filter bar height dynamically with CSS variable --filter-bar-height
 * and direct inline styling on .map-panel.
 * Ensures sticky map and its top toolbar are never clipped or pushed underneath.
 */
function setupFilterBarHeightSync() {
  const filterSection = document.querySelector('.filter-section');
  const mapPanel = document.querySelector('.map-panel');
  if (!filterSection || !mapPanel) return;

  const updateHeight = () => {
    if (window.innerWidth <= 1080) {
      mapPanel.style.top = '';
      mapPanel.style.height = '';
      return;
    }

    const height = Math.ceil(filterSection.getBoundingClientRect().height);
    document.documentElement.style.setProperty('--filter-bar-height', `${height}px`);
    mapPanel.style.top = `${height}px`;
    mapPanel.style.height = `calc(100dvh - ${height}px)`;
    if (mapInstance) {
      mapInstance.invalidateSize();
    }
  };

  updateHeight();

  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(() => updateHeight());
    observer.observe(filterSection);
  }
  window.addEventListener('resize', updateHeight, { passive: true });
}

/**
 * Initialize App & Load Curated Event Data
 */
async function initApp() {
  setupDialogLightDismissFallback();
  setupFilterBarHeightSync();
  initMap();

  try {
    const response = await fetch('data/events.json');
    const data = await response.json();
    allEvents = data.events || [];

    if (data.metadata?.sources_checked_count) {
      const headerCountEl = document.getElementById('meta-sources-count');
      if (headerCountEl) {
        headerCountEl.textContent = `${data.metadata.sources_checked_count} regionale Quellen`;
      }
    }

    if (data.metadata?.weekend_label) {
      document.getElementById('weekend-badge-text').textContent = data.metadata.weekend_label;
    }
    if (data.metadata?.last_updated_display) {
      const datePart = data.metadata.last_updated_display.split(' ')[0];
      document.getElementById('feed-updated').textContent = `Stand: ${datePart}`;
    }
  } catch (err) {
    console.error('Failed to load data/events.json:', err);
  }

  populateInfoDialogs();
  updateUI();

  // Wire Filter Controls
  const form = document.getElementById('filter-form');
  form.addEventListener('input', () => updateUI());
  form.addEventListener('change', () => updateUI());
  form.addEventListener('submit', (e) => e.preventDefault());

  // Wire Quick Preset Chips (multi-select / combinable)
  const presetBtns = document.querySelectorAll('.chip-btn[data-preset]');
  presetBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const preset = btn.dataset.preset;
      if (activePresets.has(preset)) {
        activePresets.delete(preset);
        btn.setAttribute('aria-pressed', 'false');
      } else {
        activePresets.add(preset);
        btn.setAttribute('aria-pressed', 'true');
      }
      updateUI();
    });
  });

  // Wire Reset Button
  document.getElementById('btn-reset-filters').addEventListener('click', () => {
    form.reset();
    activePresets.clear();
    presetBtns.forEach((b) => b.setAttribute('aria-pressed', 'false'));
    updateUI();
  });

  // Wire Dialog Modals
  document.getElementById('btn-open-methodology').addEventListener('click', () => {
    document.getElementById('methodology-dialog').showModal();
  });

  // Wire Back to Top Floating Button (Modern Web Guidance: scroll-position-aware-elements)
  initBackToTop();
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

document.addEventListener('DOMContentLoaded', initApp);
