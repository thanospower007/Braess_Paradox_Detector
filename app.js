/* =====================================================================
 * Detector de Paradoja de Braess — app.js v2
 *
 * Cambios respecto a app.js original. Cada [FIX-N] es trazable a un
 * hallazgo del Reporte_Diagnostico_Frontend.pdf:
 *
 *   [FIX-1]  Bug "NaN min" — lee los campos reales del backend v2
 *            (study_metrics.n_scenarios_tested, etc.) y maneja nulos.
 *   [FIX-2]  XSS — todos los datos del backend pasan por escapeHTML()
 *            antes de inyectarse al DOM. Popups Leaflet también.
 *   [FIX-4]  displayNetwork() ahora añade la red base al mapa.
 *   [FIX-6]  AbortController para cancelar simulación.
 *   [FIX-7]  Parámetros configurables enviados en el payload POST.
 *   [FIX-8]  Renderizado estructurado de IC95%, p-value y badge FDR.
 *   [FIX-10] Encapsulación en IIFE; sin variables globales.
 *   [FIX-10.4] revokeObjectURL en todos los exports.
 *   [FIX-10.5] Escape correcto del CSV (comillas dobles para todo campo).
 *   [FIX-10.9] Default del mapa centrado en Medellín (no NYC).
 *   [FIX-10.16] Manejo de total_steps=0 y otros bordes en updateProgress.
 * ===================================================================== */

(function () {
    'use strict';

    // ---------- Estado encapsulado ----------
    const state = {
        map: null,
        socket: null,
        recommendationLayers: null,
        networkLayer: null,
        currentBounds: null,
        simulationRunning: false,
        abortController: null,
        lastResults: null,
        lastRecommendations: [],
    };

    // ---------- Constantes ----------
    const MEDELLIN_CENTER = [6.2476, -75.5658];
    const DEFAULT_ZOOM = 12;
    const TILE_URL = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    const TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

    // =====================================================================
    // [FIX-2] Utilidades de seguridad: escape de HTML y CSV
    // =====================================================================

    /**
     * Escapa caracteres especiales de HTML. Toda interpolación de datos
     * del backend en innerHTML debe pasar por aquí.
     */
    function escapeHTML(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    /** Alias corto, para mantener legibilidad en plantillas. */
    const e = escapeHTML;

    /** Escape de un valor para que sea seguro en una celda CSV. */
    function csvCell(value) {
        if (value === null || value === undefined) return '';
        const s = String(value);
        // Cualquier valor potencialmente problemático va entre comillas dobles
        // y se escapa el doble-comilla duplicándolo (RFC 4180).
        return '"' + s.replace(/"/g, '""') + '"';
    }

    /** Formatea un número con N decimales o devuelve "—" si es inválido. */
    function fmtNum(value, decimals = 2) {
        if (value === null || value === undefined || !isFinite(value)) return '—';
        return Number(value).toFixed(decimals);
    }

    /** Formatea p-value con notación adaptativa. */
    function fmtPValue(p) {
        if (p === null || p === undefined || !isFinite(p)) return '—';
        if (p < 0.0001) return p.toExponential(2);
        return Number(p).toFixed(4);
    }

    // =====================================================================
    // Inicialización
    // =====================================================================

    function init() {
        initMap();
        setupEventListeners();
        connectWebSocket();
    }

    function initMap() {
        // [FIX-10.9] centrar en Medellín por defecto, coherente con el input.
        state.map = L.map('map').setView(MEDELLIN_CENTER, DEFAULT_ZOOM);
        L.tileLayer(TILE_URL, { attribution: TILE_ATTR, maxZoom: 19 }).addTo(state.map);
        state.recommendationLayers = L.layerGroup().addTo(state.map);
    }

    function setupEventListeners() {
        document.getElementById('simulate-btn').addEventListener('click', runSimulation);
        document.getElementById('cancel-btn').addEventListener('click', cancelSimulation);
        document.getElementById('export-geojson').addEventListener('click', () => exportResults('geojson'));
        document.getElementById('export-csv').addEventListener('click', () => exportResults('csv'));
        document.getElementById('export-modified-graph').addEventListener('click', exportModifiedGraph);

        document.getElementById('place-input').addEventListener('keypress', (ev) => {
            if (ev.key === 'Enter') runSimulation();
        });

        const showMoreBtn = document.getElementById('show-more-btn');
        showMoreBtn.addEventListener('click', () => {
            const hidden = document.getElementById('hidden-recommendations');
            if (!hidden) return;
            const isHidden = hidden.hasAttribute('hidden');
            if (isHidden) {
                hidden.removeAttribute('hidden');
                showMoreBtn.textContent = 'Ver menos';
                showMoreBtn.setAttribute('aria-expanded', 'true');
            } else {
                hidden.setAttribute('hidden', '');
                showMoreBtn.textContent = 'Ver más';
                showMoreBtn.setAttribute('aria-expanded', 'false');
            }
        });
    }

    function connectWebSocket() {
        if (typeof io === 'undefined') {
            console.warn('socket.io no disponible; el progreso en tiempo real estará desactivado.');
            return;
        }
        state.socket = io({ reconnection: true, reconnectionAttempts: 5 });
        state.socket.on('connect', () => console.log('WebSocket conectado.'));
        state.socket.on('simulation_update', updateProgress);
        state.socket.on('disconnect', () => console.log('WebSocket desconectado.'));
        state.socket.on('connect_error', (err) => console.warn('WebSocket error:', err.message));
    }

    // =====================================================================
    // UI helpers
    // =====================================================================

    function showStatus(message) {
        document.getElementById('status-message').textContent = message;
    }

    function setButtonRunning(running) {
        const btn = document.getElementById('simulate-btn');
        const cancel = document.getElementById('cancel-btn');
        if (running) {
            btn.disabled = true;
            btn.classList.add('running');
            btn.classList.remove('success');
            btn.textContent = 'Simulando…';
            cancel.hidden = false;
        } else {
            btn.disabled = false;
            btn.classList.remove('running');
            btn.textContent = 'Ejecutar simulación';
            cancel.hidden = true;
        }
    }

    function setExportEnabled(enabled) {
        ['export-geojson', 'export-csv', 'export-modified-graph'].forEach(id => {
            document.getElementById(id).disabled = !enabled;
        });
    }

    // [FIX-10.16] Manejo robusto de updateProgress.
    // [FIX-14] Log de actividad acumulativo. Mantiene los últimos N mensajes
    // de fase para que el usuario vea exactamente qué hizo el backend.
    const activityLog = [];
    const ACTIVITY_LOG_MAX = 50;
    let lastPhase = null;

    function appendActivityLog(message, phase) {
        const time = new Date().toTimeString().slice(0, 8);
        activityLog.push({ time, message, phase });
        while (activityLog.length > ACTIVITY_LOG_MAX) activityLog.shift();

        const logEl = document.getElementById('activity-log');
        if (!logEl) return;

        // Solo agregamos al DOM si la fase cambió, para no spamear
        const lastLi = logEl.querySelector('li:last-child');
        const lastLiTxt = lastLi ? lastLi.dataset.message : null;
        if (lastLiTxt === message) return;  // mismo mensaje, no duplicar

        const li = document.createElement('li');
        li.dataset.message = message;
        li.dataset.phase = phase || '';
        li.innerHTML = `<span class="log-time">${e(time)}</span> ` +
                       `<span class="log-phase log-phase-${e(phase || 'misc')}">${e(phase || 'misc')}</span> ` +
                       `<span class="log-message">${e(message)}</span>`;
        logEl.appendChild(li);
        // Mantener solo los últimos en DOM también
        while (logEl.children.length > ACTIVITY_LOG_MAX) logEl.removeChild(logEl.firstChild);
        logEl.scrollTop = logEl.scrollHeight;
    }

    function clearActivityLog() {
        activityLog.length = 0;
        const logEl = document.getElementById('activity-log');
        if (logEl) logEl.innerHTML = '';
        lastPhase = null;
    }

    function updateProgress(data) {
        const total = Math.max(1, Number(data.total_steps) || 1);
        const step = Math.max(0, Number(data.step) || 0);
        const pct = Math.min(100, (step / total) * 100);
        const phase = data.phase || null;

        const fill = document.getElementById('progress-fill');
        const bar = document.getElementById('progress-bar');
        fill.style.width = pct + '%';
        bar.setAttribute('aria-valuenow', String(Math.round(pct)));

        const detail = document.getElementById('progress-detail');
        detail.textContent = data.status ? `${data.status}` : '';

        // Cambio de fase: clase visual para que se vea el contexto
        if (phase && phase !== lastPhase) {
            fill.dataset.phase = phase;
            lastPhase = phase;
        }

        if (step >= total && step > 0 && phase === 'done') {
            fill.classList.add('complete');
        } else {
            fill.classList.remove('complete');
        }

        if (data.status) {
            showStatus(data.status);
            appendActivityLog(data.status, phase);
        }
    }

    /**
     * Lee parámetros del usuario. Ahora devuelve solo los campos que el
     * usuario llenó explícitamente (input.value !== ''); los vacíos se
     * omiten para que el backend aplique auto-tune si está activo.
     */
    function readParams() {
        const numOpt = (id) => {
            const el = document.getElementById(id);
            const v = el.value;
            return (v === '' || v === null) ? undefined : Number(v);
        };
        const params = {};
        const fields = {
            n_trips: 'param-n-trips',
            n_replications: 'param-n-replications',
            min_path_len_nodes: 'param-min-path-len',
            duration_minutes: 'param-duration',
            min_effect_size_pct: 'param-min-effect',
            fdr_alpha: 'param-fdr-alpha',
        };
        for (const [key, id] of Object.entries(fields)) {
            const v = numOpt(id);
            if (v !== undefined && !Number.isNaN(v)) params[key] = v;
        }
        return params;
    }

    function readAutoTuneFlag() {
        const cb = document.getElementById('param-auto-tune');
        return cb ? cb.checked : true;
    }

    function readBudget() {
        const el = document.getElementById('param-budget');
        if (!el || el.value === '') return 30;
        const v = Number(el.value);
        return Number.isFinite(v) && v > 0 ? v : 30;
    }

    function readFallbackRadius() {
        const el = document.getElementById('param-fallback-radius');
        if (!el || el.value === '') return 1500;
        const v = Number(el.value);
        return Number.isFinite(v) && v > 0 ? v : 1500;
    }

    // =====================================================================
    // Simulación
    // =====================================================================

    /**
     * [FIX-19] Pre-centra el mapa en el lugar ANTES de la simulación.
     * Usa Nominatim directamente (no nuestro backend) para no esperar la
     * descarga del grafo entero. El centrado es preview; cuando la simulación
     * termina, displayNetwork() ajusta el bounds al área real descargada.
     *
     * No bloquea si Nominatim falla — la simulación procede igual.
     */
    function preCenterMap(place) {
        const url = 'https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' +
                    encodeURIComponent(place);
        return fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(r => r.json())
            .then(arr => {
                if (!arr || arr.length === 0) return null;
                const item = arr[0];
                const lat = parseFloat(item.lat);
                const lon = parseFloat(item.lon);
                if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

                // Si Nominatim devuelve bounding box, ajusta a ella.
                // Si no, centra con un zoom razonable.
                if (item.boundingbox && item.boundingbox.length === 4) {
                    const bb = item.boundingbox.map(parseFloat);
                    const bounds = L.latLngBounds([bb[0], bb[2]], [bb[1], bb[3]]);
                    if (bounds.isValid()) {
                        state.map.fitBounds(bounds.pad(0.05));
                        return { lat, lon, bounded: true };
                    }
                }
                state.map.setView([lat, lon], 14);
                return { lat, lon, bounded: false };
            })
            .catch(err => {
                console.warn('Pre-centrado Nominatim falló (no bloqueante):', err);
                return null;
            });
    }

    function runSimulation() {
        if (state.simulationRunning) return;

        const place = document.getElementById('place-input').value.trim();
        if (!place) {
            showStatus('Error: ingrese una ciudad o área.');
            return;
        }

        state.simulationRunning = true;
        setButtonRunning(true);
        setExportEnabled(false);
        showStatus('Localizando el lugar en el mapa…');
        document.getElementById('progress-fill').style.width = '0%';
        document.getElementById('progress-fill').classList.remove('complete');
        document.getElementById('progress-detail').textContent = '';
        clearActivityLog();

        // [FIX-19] Centrar el mapa antes de empezar (preview)
        preCenterMap(place).then(() => {
            showStatus('Descargando red y comenzando simulación…');
        });

        // [FIX-6] AbortController para permitir cancelar.
        state.abortController = new AbortController();

        const payload = {
            place: place,
            params: readParams(),
            auto_tune: readAutoTuneFlag(),
            budget_minutes: readBudget(),
            fallback_radius_m: readFallbackRadius(),
        };

        fetch('/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            signal: state.abortController.signal,
        })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(d => { throw new Error(d.error || `HTTP ${response.status}`); });
                }
                return response.json();
            })
            .then(data => {
                state.simulationRunning = false;
                setButtonRunning(false);

                if (!data.success) {
                    showStatus('Error: ' + (data.error || 'desconocido'));
                    return;
                }

                state.lastResults = data.results;
                state.lastRecommendations = data.recommendations || [];

                showStatus('Simulación completada.');
                displayNetwork(data.edges);
                displayMetrics(data.results);
                displayRecommendations(state.lastRecommendations);
                displayRecommendationsOnMap(state.lastRecommendations);
                displayAutoTuneSummary(data.params_used, data.params_meta, data.download_info);

                setExportEnabled(state.lastRecommendations.length > 0);

                const btn = document.getElementById('simulate-btn');
                btn.classList.add('success');
                btn.textContent = '¡Simulación completada!';
                setTimeout(() => {
                    btn.classList.remove('success');
                    btn.textContent = 'Ejecutar simulación';
                }, 2200);
            })
            .catch(err => {
                state.simulationRunning = false;
                setButtonRunning(false);
                if (err.name === 'AbortError') {
                    showStatus('Simulación cancelada por el usuario.');
                } else {
                    console.error('Error de simulación:', err);
                    showStatus('Error: ' + err.message);
                }
            });
    }

    function cancelSimulation() {
        if (state.abortController) {
            state.abortController.abort();
            state.abortController = null;
        }
    }

    // =====================================================================
    // Visualización: red base
    // =====================================================================

    // [FIX-4] Ahora SÍ añade la red base al mapa.
    function displayNetwork(edgesGeoJSON) {
        // Limpiar capas previas (excepto teselas y recomendaciones)
        if (state.networkLayer) {
            state.map.removeLayer(state.networkLayer);
            state.networkLayer = null;
        }
        state.recommendationLayers.clearLayers();

        if (!edgesGeoJSON || !edgesGeoJSON.features || edgesGeoJSON.features.length === 0) return;

        state.networkLayer = L.geoJSON(edgesGeoJSON, {
            style: { color: '#a0aec0', weight: 2, opacity: 0.65 },
            interactive: false,  // no roba clicks a las recomendaciones
        }).addTo(state.map);

        if (state.networkLayer.getBounds().isValid()) {
            state.currentBounds = state.networkLayer.getBounds();
            state.map.fitBounds(state.currentBounds.pad(0.05));
        }
    }

    // =====================================================================
    // [FIX-1] Visualización: métricas — lee campos reales del backend v2
    // =====================================================================

    function displayMetrics(results) {
        const content = document.getElementById('metrics-content');
        if (!results || !results.base || !results.study_metrics) {
            content.innerHTML = '<p class="placeholder">No hay métricas disponibles.</p>';
            return;
        }
        const base = results.base;
        const sm = results.study_metrics;

        // Datos del backend v2 (los campos correctos):
        //   base.mean_avg_travel_time, mean_completed_trips, mean_total_travel_time,
        //        mean_vmt, cv_avg_travel_time_pct
        //   sm.n_scenarios_tested, n_scenarios_significant_fdr, n_recommendations,
        //      fdr_alpha, min_effect_size_pct, n_replications_per_scenario,
        //      n_trips, min_path_len_nodes, percent_significant
        // Para compatibilidad hacia atrás con el backend antiguo, usamos
        // accesos opcionales con fallback "—".
        const m = (label, value, opts = {}) => {
            const cls = opts.highlight ? ' highlight' : '';
            return `
                <div class="metric-item${cls}">
                    <span class="metric-label">${e(label)}:</span>
                    <span class="metric-value">${e(value)}</span>
                </div>`;
        };

        const att = base.mean_avg_travel_time ?? base.avg_travel_time;
        const trips = base.mean_completed_trips ?? base.completed_trips;
        const cv = base.cv_avg_travel_time_pct;
        const nReps = sm.n_replications_per_scenario;
        const nTested = sm.n_scenarios_tested ?? sm.changes_studied;
        const nSig = sm.n_scenarios_significant_fdr;
        const nRecs = sm.n_recommendations ?? sm.total_recommendations;
        const pctSig = sm.percent_significant ?? sm.percent_with_improvement;

        let html = m('Tiempo promedio de viaje base (ATT)', `${fmtNum(att, 1)} s`);
        html += m('Viajes completados', `${fmtNum(trips, 0)}`);
        if (cv !== undefined) {
            html += m('Variabilidad entre réplicas (CV)', `${fmtNum(cv, 2)} %`);
        }
        if (nReps !== undefined) {
            html += m('Réplicas por escenario', `${fmtNum(nReps, 0)}`);
        }
        html += m('Escenarios evaluados', `${fmtNum(nTested, 0)}`);
        if (nSig !== undefined) {
            html += m('Escenarios FDR-significativos', `${fmtNum(nSig, 0)}`);
        }
        if (pctSig !== undefined) {
            html += m('% escenarios significativos', `${fmtNum(pctSig, 1)} %`);
        }
        html += m('Recomendaciones finales', `${fmtNum(nRecs, 0)}`, { highlight: true });

        if (sm.fdr_alpha !== undefined && sm.min_effect_size_pct !== undefined) {
            html += `<div class="recommendation-justification" style="margin-top:8px">
                Filtros aplicados: FDR α = ${e(fmtNum(sm.fdr_alpha, 3))},
                efecto mínimo = ${e(fmtNum(sm.min_effect_size_pct, 1))}%.
            </div>`;
        }

        content.innerHTML = html;
    }

    // =====================================================================
    // [FIX-12] Resumen del auto-tune: muestra los parámetros que el backend
    // sugirió, con detalles de tiempo estimado. También pre-llena los
    // placeholders de los inputs vacíos para que el usuario los vea.
    // =====================================================================

    function displayAutoTuneSummary(paramsUsed, paramsMeta, downloadInfo) {
        const box = document.getElementById('auto-tune-summary');
        const content = document.getElementById('auto-tune-summary-content');
        if (!box || !content || !paramsUsed || !paramsMeta) return;

        // Aún si auto NO se usó, queremos mostrar info de descarga si fue por fallback.
        const showSummary = paramsMeta._auto_tuned ||
            (downloadInfo && downloadInfo.method === 'point_radius');

        if (!showSummary) {
            box.hidden = true;
            return;
        }

        // Llenar placeholders de inputs vacíos con los valores auto sugeridos.
        if (paramsMeta._auto_tuned) {
            const fields = {
                'param-n-trips': paramsUsed.n_trips,
                'param-n-replications': paramsUsed.n_replications,
                'param-min-path-len': paramsUsed.min_path_len_nodes,
                'param-duration': paramsUsed.duration_minutes,
                'param-min-effect': paramsUsed.min_effect_size_pct,
                'param-fdr-alpha': paramsUsed.fdr_alpha,
            };
            for (const [id, value] of Object.entries(fields)) {
                const el = document.getElementById(id);
                if (el && el.value === '') el.placeholder = String(value);
            }
        }

        // Construir resumen
        let html = '';

        // Sección "Cómo se descargó la red"  [FIX-13]
        if (downloadInfo) {
            if (downloadInfo.method === 'point_radius') {
                const lat = downloadInfo.center ? downloadInfo.center[0].toFixed(4) : '?';
                const lon = downloadInfo.center ? downloadInfo.center[1].toFixed(4) : '?';
                html += `<p class="info-note">
                    ℹ El lugar no resolvió a un polígono administrativo. Se descargó la
                    red vial en un radio de <strong>${e(downloadInfo.fallback_radius_m)} m</strong>
                    alrededor de (${e(lat)}, ${e(lon)}). Si el área es incorrecta, ajuste
                    el "Radio de fallback" o use un nombre más específico.
                </p>`;
            }
        }

        // Sección de auto-tune (si aplica)
        if (paramsMeta._auto_tuned) {
            const items = [
                ['Red analizada', `${e(fmtNum(paramsMeta._graph_n_nodes, 0))} nodos, ${e(fmtNum(paramsMeta._graph_n_edges, 0))} aristas`],
                ['Diámetro estimado', `${e(fmtNum(paramsMeta._graph_diameter_est, 0))} nodos`],
                ['Viajes simulados', e(fmtNum(paramsUsed.n_trips, 0))],
                ['Réplicas por escenario', e(fmtNum(paramsUsed.n_replications, 0))],
                ['Long. mín. ruta', `${e(fmtNum(paramsUsed.min_path_len_nodes, 0))} nodos`],
                ['Duración simulada', `${e(fmtNum(paramsUsed.duration_minutes, 0))} min`],
                ['Adiciones probadas', e(fmtNum(paramsUsed.max_addition_candidates, 0))],
                ['Simulaciones totales', e(fmtNum(paramsMeta._n_total_sims, 0))],
                ['Tiempo paralelo estimado', `${e(fmtNum(paramsMeta._estimated_parallel_minutes, 1))} min (en ${e(fmtNum(paramsMeta._n_jobs_used, 0))} cores)`],
            ];
            html += '<dl class="auto-tune-list">';
            for (const [label, value] of items) {
                html += `<dt>${e(label)}</dt><dd>${value}</dd>`;
            }
            html += '</dl>';

            if (paramsMeta._sampling_recommended) {
                html += `<p class="warning-note">
                    ⚠ Esta red excede el presupuesto de ${e(fmtNum(paramsMeta._budget_minutes, 0))} min.
                    Considere subdividir la zona o aumentar el tiempo objetivo.
                </p>`;
            }
        }

        content.innerHTML = html;
        box.hidden = false;
    }

    /**
     * Sanitiza un valor de color para uso seguro en atributo style.
     * Acepta solo #rrggbb o #rgb (hex). Si no coincide, devuelve cadena vacía
     * para evitar inyección CSS vía data del backend.
     */
    function safeColor(value) {
        if (typeof value !== 'string') return '';
        return /^#[0-9a-fA-F]{3,8}$/.test(value) ? value : '';
    }

    function buildRecommendationHTML(rec) {
        const actionClass = rec.action === 'remove' ? 'remove' : 'add';
        const sign = rec.impact_pct >= 0 ? '+' : '';

        // [FIX-17] El color del borde de la tarjeta debe coincidir con el del
        // mapa. El backend asigna el color por categoría (high/medium/low) y
        // acción (remove/add). Lo aplicamos como inline style validado.
        const color = safeColor(rec.color);
        const borderStyle = color ? `style="border-left-color: ${color}"` : '';

        // Estadísticas opcionales del backend v2
        let statsHTML = '';
        if (rec.ci95_lower !== undefined && rec.ci95_upper !== undefined) {
            statsHTML += `<span class="stat" title="Intervalo de confianza al 95% del efecto en ATT">
                IC95% [${e(fmtNum(rec.ci95_lower, 2))}, ${e(fmtNum(rec.ci95_upper, 2))}]
            </span>`;
        }
        if (rec.p_value !== undefined) {
            statsHTML += `<span class="stat" title="p-value del test de Wilcoxon pareado">
                p = ${e(fmtPValue(rec.p_value))}
            </span>`;
        }
        statsHTML += `<span class="fdr-badge">FDR ✓</span>`;

        // [FIX-18] Mostrar el ID raw (e.g. "111_222_0") visible además del label.
        // El ID viene de OSM y permite trazabilidad: el usuario puede buscarlo
        // en OpenStreetMap o copiarlo a una consulta GeoJSON.
        const idChip = rec.osmid_raw
            ? `<span class="osmid-chip" title="Identificador interno (OSM)">ID: ${e(rec.osmid_raw)}</span>`
            : '';

        return `
            <div class="recommendation-item ${e(actionClass)}" ${borderStyle}>
                <div class="recommendation-header">
                    <span class="label">${e(rec.osmid)}</span>
                    <span class="recommendation-impact">${e(sign)}${e(fmtNum(rec.impact_pct, 2))}%</span>
                </div>
                ${idChip}
                ${statsHTML ? `<div class="recommendation-stats">${statsHTML}</div>` : ''}
                <div class="recommendation-justification">${e(rec.justification || '')}</div>
            </div>`;
    }

    function displayRecommendations(recommendations) {
        const topContent = document.getElementById('top-recommendations-content');
        const allContent = document.getElementById('all-recommendations-content');
        const showMoreBtn = document.getElementById('show-more-btn');

        if (!recommendations || recommendations.length === 0) {
            topContent.innerHTML = '<p class="placeholder">No se generaron recomendaciones.</p>';
            allContent.innerHTML = '<p class="placeholder">—</p>';
            showMoreBtn.hidden = true;
            return;
        }

        const top = recommendations.slice(0, 3);
        const rest = recommendations.slice(3);

        topContent.innerHTML = top.map(buildRecommendationHTML).join('');

        if (rest.length === 0) {
            allContent.innerHTML = '<p class="placeholder">No hay más recomendaciones.</p>';
            showMoreBtn.hidden = true;
            return;
        }

        const visibleRest = rest.slice(0, 3);
        const hiddenRest = rest.slice(3);
        let restHTML = visibleRest.map(buildRecommendationHTML).join('');

        if (hiddenRest.length > 0) {
            restHTML += `<div id="hidden-recommendations" hidden>${hiddenRest.map(buildRecommendationHTML).join('')}</div>`;
            showMoreBtn.hidden = false;
            showMoreBtn.textContent = `Ver más (${hiddenRest.length})`;
            showMoreBtn.setAttribute('aria-expanded', 'false');
        } else {
            showMoreBtn.hidden = true;
        }

        allContent.innerHTML = restHTML;
    }

    // =====================================================================
    // [FIX-2] Mapa: popups con escape correcto
    // =====================================================================

    function displayRecommendationsOnMap(recommendations) {
        state.recommendationLayers.clearLayers();
        if (!recommendations || recommendations.length === 0) return;

        let bounds = null;

        recommendations.forEach(rec => {
            if (!rec.geometry || rec.geometry.length === 0) return;
            const color = rec.color || '#808080';
            const latLngs = rec.geometry.map(coord => [coord[1], coord[0]]);

            const polyline = L.polyline(latLngs, {
                color: color,
                weight: 6,
                opacity: 0.9,
                dashArray: rec.action === 'add' ? '10, 10' : null,
            });

            // Para Leaflet popups: bindPopup acepta o un string HTML, o un
            // contenido DOM. Como bindPopup string interpreta HTML, escapamos
            // todos los datos del backend antes de embeberlos.
            const sign = rec.impact_pct >= 0 ? '+' : '';
            let popupHTML = `
                <strong>Acción:</strong> ${e(rec.action === 'remove' ? 'Remover' : 'Añadir')}<br>
                <strong>ID:</strong> ${e(rec.osmid)}<br>
                <strong>Impacto en ATT:</strong> ${e(sign)}${e(fmtNum(rec.impact_pct, 2))}%<br>`;
            if (rec.ci95_lower !== undefined && rec.ci95_upper !== undefined) {
                popupHTML += `<strong>IC95%:</strong> [${e(fmtNum(rec.ci95_lower, 2))}, ${e(fmtNum(rec.ci95_upper, 2))}]<br>`;
            }
            if (rec.p_value !== undefined) {
                popupHTML += `<strong>p-value:</strong> ${e(fmtPValue(rec.p_value))}<br>`;
            }
            popupHTML += `<em>${e(rec.justification || '')}</em>`;

            polyline.bindPopup(popupHTML);
            state.recommendationLayers.addLayer(polyline);

            if (!bounds) bounds = polyline.getBounds();
            else bounds.extend(polyline.getBounds());
        });

        if (bounds && bounds.isValid()) {
            state.map.fitBounds(bounds.pad(0.15));
        }
    }

    // =====================================================================
    // Exportación
    // =====================================================================

    /** Crea y dispara una descarga vía Blob. Maneja revokeObjectURL. */
    function downloadBlob(content, mimeType, filename) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        // [FIX-10.4] revoke para liberar memoria.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    // [FIX-10.5] CSV con escape RFC 4180 correcto en TODOS los campos.
    function buildCSV(recommendations) {
        const headers = ['osmid', 'action', 'impact_pct', 'ci95_lower', 'ci95_upper', 'p_value', 'justification'];
        const lines = [headers.join(',')];
        recommendations.forEach(rec => {
            const row = [
                csvCell(rec.osmid),
                csvCell(rec.action),
                csvCell(fmtNum(rec.impact_pct, 3)),
                csvCell(rec.ci95_lower !== undefined ? fmtNum(rec.ci95_lower, 3) : ''),
                csvCell(rec.ci95_upper !== undefined ? fmtNum(rec.ci95_upper, 3) : ''),
                csvCell(rec.p_value !== undefined ? fmtPValue(rec.p_value) : ''),
                csvCell(rec.justification || ''),
            ];
            lines.push(row.join(','));
        });
        return lines.join('\n');
    }

    function buildGeoJSON(recommendations) {
        const features = recommendations
            .filter(rec => rec.geometry && rec.geometry.length > 0)
            .map(rec => ({
                type: 'Feature',
                properties: {
                    osmid: rec.osmid,
                    action: rec.action,
                    impact_pct: rec.impact_pct,
                    ci95_lower: rec.ci95_lower ?? null,
                    ci95_upper: rec.ci95_upper ?? null,
                    p_value: rec.p_value ?? null,
                    justification: rec.justification || '',
                },
                geometry: { type: 'LineString', coordinates: rec.geometry },
            }));
        return { type: 'FeatureCollection', features: features };
    }

    function exportResults(format) {
        fetch('/api/recommendations')
            .then(r => r.json())
            .then(recs => {
                if (!recs || recs.length === 0) {
                    showStatus('No hay recomendaciones para exportar.');
                    return;
                }
                if (format === 'csv') {
                    downloadBlob(buildCSV(recs), 'text/csv;charset=utf-8;', 'recommendations.csv');
                } else if (format === 'geojson') {
                    downloadBlob(JSON.stringify(buildGeoJSON(recs), null, 2),
                        'application/geo+json;charset=utf-8;', 'recommendations.geojson');
                }
            })
            .catch(err => {
                console.error('Export error:', err);
                showStatus('Falló la exportación: ' + err.message);
            });
    }

    function exportModifiedGraph() {
        fetch('/api/export/modified_graph')
            .then(response => {
                if (!response.ok) {
                    return response.json().then(d => { throw new Error(d.error || 'Falló la exportación'); });
                }
                return response.text();
            })
            .then(content => {
                downloadBlob(content, 'application/xml', 'modified_network.graphml');
            })
            .catch(err => {
                console.error('Export error:', err);
                showStatus('Falló la exportación: ' + err.message);
            });
    }

    // ---------- Boot ----------
    document.addEventListener('DOMContentLoaded', init);
})();