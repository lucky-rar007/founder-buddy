/* ═══════════════════════════════════════════════════════════════
   FOUNDER BUDDY DASHBOARD — Client-Side Application
   ═══════════════════════════════════════════════════════════════ */

// ── State ──
let dashboardState = {
    clusters: {},
    signals: [],
    events: [],
    threads: [],
    actionables: [],
    draggingIssues: [],
    stats: {}
};

// ── Initialization ──
document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
});

// ═══════════════════════════════════════════════════════════════
// DATA FETCHING
// ═══════════════════════════════════════════════════════════════

async function fetchJSON(url) {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (err) {
        console.error(`[Dashboard] Failed to fetch ${url}:`, err);
        return null;
    }
}

async function refreshDashboard() {
    const btnRefresh = document.getElementById('btn-refresh');
    if (btnRefresh) btnRefresh.disabled = true;

    try {
        // The backend exposes a single consolidated stats endpoint
        const statsRes = await fetchJSON('/api/dashboard/stats');

        if (statsRes?.success) {
            dashboardState.stats = statsRes.stats || {};
            dashboardState.actionables = statsRes.actionables || [];
            dashboardState.draggingIssues = statsRes.dragging_issues || [];
        }

        // Re-render everything
        renderStats();
        renderClusterGrid();
        renderActionables();
        renderDraggingIssues();
        renderSignalTable();
        populateSignalFilters();

    } catch (err) {
        console.error('[Dashboard] Refresh failed:', err);
    } finally {
        if (btnRefresh) btnRefresh.disabled = false;
    }
}

// ═══════════════════════════════════════════════════════════════
// STATS BAR
// ═══════════════════════════════════════════════════════════════

function renderStats() {
    const stats = dashboardState.stats;
    animateCounter('stat-threads', stats.threads || 0);
    animateCounter('stat-events', stats.events || 0);
    animateCounter('stat-signals', stats.signals || 0);
    animateCounter('stat-actionables', stats.actionables || 0);
    animateCounter('stat-dragging', stats.dragging_issues || 0);
}

function animateCounter(elementId, targetValue) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const startValue = parseInt(el.textContent) || 0;
    const duration = 600;
    const startTime = performance.now();

    function step(timestamp) {
        const elapsed = timestamp - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(startValue + (targetValue - startValue) * eased);
        el.textContent = current;

        if (progress < 1) {
            requestAnimationFrame(step);
        }
    }

    requestAnimationFrame(step);
}

// ═══════════════════════════════════════════════════════════════
// CLUSTER HEALTH GRID
// ═══════════════════════════════════════════════════════════════

function renderClusterGrid() {
    const grid = document.getElementById('cluster-grid');
    const emptyState = document.getElementById('cluster-empty');
    const countBadge = document.getElementById('cluster-count');

    // Try to build clusters from signals if we have them
    const clusters = buildClustersFromSignals();
    dashboardState.clusters = clusters;

    const clusterKeys = Object.keys(clusters);

    if (clusterKeys.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        if (countBadge) countBadge.textContent = '0 clusters';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (countBadge) countBadge.textContent = `${clusterKeys.length} clusters`;

    // Clear previous cards (but not empty state)
    const existingCards = grid.querySelectorAll('.cluster-card');
    existingCards.forEach(card => card.remove());

    clusterKeys.forEach((key, index) => {
        const cluster = clusters[key];
        const card = createClusterCard(key, cluster, index);
        grid.appendChild(card);
    });
}

function buildClustersFromSignals() {
    // Group signals by cluster_type and calculate health metrics
    const signals = dashboardState.signals;
    if (signals.length === 0) return {};

    const clusterMap = {};

    // Default clusters
    const defaultClusters = [
        'project_health', 'client_relations', 'team_dynamics',
        'delivery_risk', 'process_compliance', 'resource_management'
    ];

    defaultClusters.forEach(ct => {
        clusterMap[ct] = {
            name: ct.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            signals: [],
            health_score: 50,
            status: 'Stable',
            confidence: 1.0,
            summary: 'No signals recorded for this cluster yet.'
        };
    });

    signals.forEach(sig => {
        const ct = sig.cluster_type;
        if (!clusterMap[ct]) {
            clusterMap[ct] = {
                name: ct.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
                signals: [],
                health_score: 50,
                status: 'Stable',
                confidence: 0.5,
                summary: 'Dynamically discovered cluster.'
            };
        }
        clusterMap[ct].signals.push(sig);
    });

    // Calculate health scores from signals
    Object.keys(clusterMap).forEach(ct => {
        const sigs = clusterMap[ct].signals;
        if (sigs.length === 0) return;

        let totalStrength = 0;
        let totalRelevance = 0;

        sigs.forEach(s => {
            totalStrength += parseFloat(s.decayed_strength || s.strength || 0);
            totalRelevance += parseFloat(s.relevance_score || 0.5);
        });

        const avgStrength = totalStrength / sigs.length;
        const avgRelevance = totalRelevance / sigs.length;

        // Map average strength (-1 to 1) to health score (0 to 100)
        // Positive strength = healthy, negative = unhealthy
        let healthScore = Math.round(50 + (avgStrength * 50));
        healthScore = Math.max(0, Math.min(100, healthScore));

        let status = 'Stable';
        if (healthScore >= 70) status = 'Healthy';
        else if (healthScore >= 50) status = 'Stable';
        else if (healthScore >= 30) status = 'Warning';
        else status = 'Critical';

        clusterMap[ct].health_score = healthScore;
        clusterMap[ct].status = status;
        clusterMap[ct].confidence = avgRelevance;
        clusterMap[ct].signal_count = sigs.length;
    });

    return clusterMap;
}

function createClusterCard(key, cluster, index) {
    const card = document.createElement('div');
    const statusClass = (cluster.status || 'stable').toLowerCase();
    card.className = `cluster-card ${statusClass}`;
    card.style.animationDelay = `${index * 0.05}s`;
    card.onclick = () => showClusterSignals(key);

    const score = cluster.health_score || 50;
    const scoreColor = getScoreColor(score);

    card.innerHTML = `
        <div class="cluster-card-header">
            <div>
                <div class="cluster-name">${cluster.name || key}</div>
                <div class="cluster-category">${cluster.category || ''}</div>
            </div>
            <div class="cluster-score-container">
                <div class="cluster-score-ring score-${statusClass}">
                    <span class="cluster-score-value">${score}</span>
                </div>
            </div>
        </div>
        <span class="cluster-status-badge ${statusClass}">${cluster.status || 'Stable'}</span>
        <div class="cluster-summary">${cluster.summary || 'No data available.'}</div>
        <div class="cluster-meta">
            <span>${(cluster.signals || []).length} signals</span>
            <span>${Math.round((cluster.confidence || 0.5) * 100)}% confidence</span>
        </div>
    `;

    return card;
}

function getScoreColor(score) {
    if (score >= 70) return '#10b981';
    if (score >= 50) return '#3b82f6';
    if (score >= 30) return '#f59e0b';
    return '#ef4444';
}

function showClusterSignals(clusterType) {
    // Filter signal table to this cluster
    const filterEl = document.getElementById('signal-filter-cluster');
    if (filterEl) {
        filterEl.value = clusterType;
        filterSignals();
    }
    // Scroll to signal section
    document.getElementById('signal-section')?.scrollIntoView({ behavior: 'smooth' });
}

// ═══════════════════════════════════════════════════════════════
// ACTIONABLES FEED
// ═══════════════════════════════════════════════════════════════

function renderActionables() {
    const list = document.getElementById('actionables-list');
    const emptyState = document.getElementById('actionables-empty');
    const countBadge = document.getElementById('actionables-count');

    const actionables = dashboardState.actionables;

    if (actionables.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        if (countBadge) countBadge.textContent = '0 items';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (countBadge) countBadge.textContent = `${actionables.length} items`;

    // Clear and rebuild
    list.innerHTML = '';

    // Sort by priority
    const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    const sorted = [...actionables].sort((a, b) =>
        (priorityOrder[a.priority] || 3) - (priorityOrder[b.priority] || 3)
    );

    sorted.forEach(act => {
        const item = document.createElement('div');
        item.className = 'actionable-item';
        item.innerHTML = `
            <div class="actionable-priority ${act.priority || 'medium'}"></div>
            <div class="actionable-content">
                <div class="actionable-title">${escapeHtml(act.title || 'Untitled Action')}</div>
                <div class="actionable-desc">${escapeHtml(act.description || '')}</div>
                <div class="actionable-meta">
                    <span class="actionable-tag ${act.priority || 'medium'}">${(act.priority || 'medium').toUpperCase()}</span>
                    <span style="color: var(--text-muted);">${act.source || ''}</span>
                </div>
            </div>
        `;
        list.appendChild(item);
    });
}

// ═══════════════════════════════════════════════════════════════
// DRAGGING ISSUES
// ═══════════════════════════════════════════════════════════════

function renderDraggingIssues() {
    const list = document.getElementById('dragging-list');
    const emptyState = document.getElementById('dragging-empty');
    const countBadge = document.getElementById('dragging-count');

    const issues = dashboardState.draggingIssues;

    if (issues.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        if (countBadge) countBadge.textContent = '0 issues';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (countBadge) countBadge.textContent = `${issues.length} issues`;

    list.innerHTML = '';

    issues.forEach(issue => {
        const item = document.createElement('div');
        item.className = `dragging-item ${issue.severity || 'medium'}`;
        item.innerHTML = `
            <div class="dragging-header">
                <div class="dragging-title">${escapeHtml(issue.title || 'Unresolved Issue')}</div>
            </div>
            <div class="dragging-desc">${escapeHtml(issue.description || '')}</div>
        `;
        list.appendChild(item);
    });
}

// ═══════════════════════════════════════════════════════════════
// SIGNAL EXPLORER TABLE
// ═══════════════════════════════════════════════════════════════

function renderSignalTable() {
    const tbody = document.getElementById('signal-tbody');
    const emptyState = document.getElementById('signal-empty');
    const table = document.getElementById('signal-table');

    const signals = dashboardState.signals;

    if (signals.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        if (table) table.style.display = 'none';
        return;
    }

    if (emptyState) emptyState.style.display = 'none';
    if (table) table.style.display = 'table';

    tbody.innerHTML = '';

    // Enrich signals with event data
    const eventsMap = {};
    dashboardState.events.forEach(e => { eventsMap[e.event_id] = e; });

    const threadsMap = {};
    dashboardState.threads.forEach(t => { threadsMap[t.thread_id] = t; });

    signals.forEach(sig => {
        const event = eventsMap[sig.event_id] || {};
        const thread = threadsMap[sig.thread_id] || {};
        const strength = parseFloat(sig.strength || 0);
        const decayed = parseFloat(sig.decayed_strength || 0);
        const direction = strength >= 0 ? (strength > 0 ? 'positive' : 'neutral') : 'negative';
        const strengthPct = Math.min(Math.abs(strength) * 100, 100);
        const decayedPct = Math.min(Math.abs(decayed) * 100, 100);

        const source = sig.thread_source || thread.source || 'unknown';

        const row = document.createElement('tr');
        row.dataset.cluster = sig.cluster_type || '';
        row.dataset.direction = direction;

        row.innerHTML = `
            <td><span class="signal-type-badge">${formatSignalType(sig.signal_type)}</span></td>
            <td><span class="signal-cluster-badge">${formatClusterType(sig.cluster_type)}</span></td>
            <td>
                <div class="strength-bar">
                    <div class="strength-bar-track">
                        <div class="strength-bar-fill ${direction}" style="width: ${strengthPct}%"></div>
                    </div>
                    <span>${strength.toFixed(2)}</span>
                </div>
            </td>
            <td>
                <div class="strength-bar">
                    <div class="strength-bar-track">
                        <div class="strength-bar-fill ${direction}" style="width: ${decayedPct}%"></div>
                    </div>
                    <span>${decayed.toFixed(3)}</span>
                </div>
            </td>
            <td>${(parseFloat(sig.relevance_score || 0) * 100).toFixed(0)}%</td>
            <td>${(parseFloat(sig.confidence || 0) * 100).toFixed(0)}%</td>
            <td><span class="signal-source-badge ${source}">${source === 'teams' ? 'Teams' : source === 'outlook' ? 'Outlook' : source}</span></td>
            <td style="font-size: 0.75rem; color: var(--text-muted);">${formatDate(sig.timestamp)}</td>
            <td><button class="btn-detail" onclick="showSignalDetail('${sig.signal_id}')">View</button></td>
        `;

        tbody.appendChild(row);
    });
}

function populateSignalFilters() {
    const filterEl = document.getElementById('signal-filter-cluster');
    if (!filterEl) return;

    // Preserve current selection
    const currentValue = filterEl.value;

    // Clear options except "All"
    filterEl.innerHTML = '<option value="all">All Clusters</option>';

    const clusters = new Set();
    dashboardState.signals.forEach(s => {
        if (s.cluster_type) clusters.add(s.cluster_type);
    });

    clusters.forEach(ct => {
        const option = document.createElement('option');
        option.value = ct;
        option.textContent = formatClusterType(ct);
        filterEl.appendChild(option);
    });

    // Restore selection
    filterEl.value = currentValue || 'all';
}

function filterSignals() {
    const clusterFilter = document.getElementById('signal-filter-cluster')?.value || 'all';
    const directionFilter = document.getElementById('signal-filter-direction')?.value || 'all';

    const rows = document.querySelectorAll('#signal-tbody tr');

    rows.forEach(row => {
        const matchesCluster = clusterFilter === 'all' || row.dataset.cluster === clusterFilter;
        const matchesDirection = directionFilter === 'all' || row.dataset.direction === directionFilter;

        row.style.display = (matchesCluster && matchesDirection) ? '' : 'none';
    });
}

function showSignalDetail(signalId) {
    const signal = dashboardState.signals.find(s => s.signal_id === signalId);
    if (!signal) return;

    const event = dashboardState.events.find(e => e.event_id === signal.event_id) || {};
    const thread = dashboardState.threads.find(t => t.thread_id === signal.thread_id) || {};

    const modal = document.getElementById('signal-detail-modal');
    const title = document.getElementById('signal-detail-title');
    const body = document.getElementById('signal-detail-body');

    title.textContent = `Signal: ${formatSignalType(signal.signal_type)}`;

    body.innerHTML = `
        <div class="detail-grid">
            <div class="detail-item">
                <div class="detail-label">Signal Type</div>
                <div class="detail-value">${formatSignalType(signal.signal_type)}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Cluster</div>
                <div class="detail-value">${formatClusterType(signal.cluster_type)}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Strength</div>
                <div class="detail-value">${parseFloat(signal.strength || 0).toFixed(3)}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Decayed Strength</div>
                <div class="detail-value">${parseFloat(signal.decayed_strength || 0).toFixed(4)}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Relevance</div>
                <div class="detail-value">${(parseFloat(signal.relevance_score || 0) * 100).toFixed(0)}%</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Confidence</div>
                <div class="detail-value">${(parseFloat(signal.confidence || 0) * 100).toFixed(0)}%</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Persistence</div>
                <div class="detail-value">${parseFloat(signal.persistence || 0).toFixed(2)}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Decay Rate</div>
                <div class="detail-value">${parseFloat(signal.decay_rate || 0).toFixed(4)}/day</div>
            </div>
            <div class="detail-item detail-full">
                <div class="detail-label">Event Summary</div>
                <div class="detail-value" style="font-weight: 400; font-size: 0.82rem;">${escapeHtml(event.summary || signal.event_summary || 'N/A')}</div>
            </div>
            <div class="detail-item detail-full">
                <div class="detail-label">Thread Subject</div>
                <div class="detail-value" style="font-weight: 400; font-size: 0.82rem;">${escapeHtml(thread.subject || signal.thread_subject || 'N/A')}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Source</div>
                <div class="detail-value">${signal.thread_source || thread.source || 'Unknown'}</div>
            </div>
            <div class="detail-item">
                <div class="detail-label">Date</div>
                <div class="detail-value">${formatDate(signal.timestamp)}</div>
            </div>
        </div>
        <div style="font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px; font-weight: 600;">TRACEABILITY CHAIN</div>
        <div class="trace-chain">
            <span class="trace-id">${signal.signal_id || 'N/A'}</span>
            <span class="trace-arrow">→</span>
            <span class="trace-id">${signal.event_id || 'N/A'}</span>
            <span class="trace-arrow">→</span>
            <span class="trace-id">${signal.thread_id || 'N/A'}</span>
        </div>
    `;

    modal.style.display = 'flex';
}

function closeSignalDetail() {
    document.getElementById('signal-detail-modal').style.display = 'none';
}

// ═══════════════════════════════════════════════════════════════
// PIPELINE EXECUTION
// ═══════════════════════════════════════════════════════════════

function runPipeline() {
    document.getElementById('pipeline-modal').style.display = 'flex';
    document.getElementById('pipeline-progress').style.display = 'none';
    document.getElementById('btn-execute-pipeline').disabled = false;
}

function closePipelineModal() {
    document.getElementById('pipeline-modal').style.display = 'none';
}

async function executePipeline() {
    const apiKeyInput = document.getElementById('api-key-input');
    const progressDiv = document.getElementById('pipeline-progress');
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');
    const executeBtn = document.getElementById('btn-execute-pipeline');
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    executeBtn.disabled = true;
    progressDiv.style.display = 'block';
    progressFill.style.width = '10%';
    progressText.textContent = 'Initializing pipeline...';
    statusDot.className = 'status-dot running';
    statusText.textContent = 'Running...';

    // Simulate progress while waiting
    let progress = 10;
    const progressInterval = setInterval(() => {
        if (progress < 90) {
            progress += Math.random() * 8;
            progressFill.style.width = `${Math.min(progress, 90)}%`;

            if (progress < 25) progressText.textContent = 'Loading conversation threads...';
            else if (progress < 45) progressText.textContent = 'Extracting events via AI...';
            else if (progress < 65) progressText.textContent = 'Clustering signals...';
            else if (progress < 80) progressText.textContent = 'Evaluating cluster health...';
            else progressText.textContent = 'Detecting dragging issues...';
        }
    }, 800);

    try {
        const body = {};
        if (apiKeyInput?.value?.trim()) {
            body.gemini_api_key = apiKeyInput.value.trim();
        }

        const response = await fetch('/api/run-pipeline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const result = await response.json();

        clearInterval(progressInterval);

        if (result.success) {
            progressFill.style.width = '100%';
            progressText.textContent = `Pipeline complete! Processed ${result.stats?.threads || 0} threads, found ${result.stats?.signals || 0} signals.`;
            statusDot.className = 'status-dot';
            statusText.textContent = 'Complete';

            // Update dashboard state from pipeline response
            if (result.clusters) dashboardState.clusters = result.clusters;
            if (result.actionables) dashboardState.actionables = result.actionables;
            if (result.dragging_issues) dashboardState.draggingIssues = result.dragging_issues;

            // Refresh to get full data
            setTimeout(() => {
                closePipelineModal();
                refreshDashboard();
            }, 1500);
        } else {
            progressFill.style.width = '100%';
            progressFill.style.background = 'var(--status-critical)';
            progressText.textContent = `Error: ${result.error || 'Pipeline failed'}`;
            statusDot.className = 'status-dot error';
            statusText.textContent = 'Error';
            executeBtn.disabled = false;
        }
    } catch (err) {
        clearInterval(progressInterval);
        progressFill.style.width = '100%';
        progressFill.style.background = 'var(--status-critical)';
        progressText.textContent = `Network error: ${err.message}`;
        statusDot.className = 'status-dot error';
        statusText.textContent = 'Error';
        executeBtn.disabled = false;
    }
}

// ═══════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatSignalType(type) {
    if (!type) return 'Unknown';
    return type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatClusterType(type) {
    if (!type) return 'Unknown';
    return type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const date = new Date(dateStr);
        if (isNaN(date.getTime())) return dateStr;

        const now = new Date();
        const diff = now - date;
        const days = Math.floor(diff / (1000 * 60 * 60 * 24));

        if (days === 0) return 'Today';
        if (days === 1) return 'Yesterday';
        if (days < 7) return `${days}d ago`;

        return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
    } catch {
        return dateStr;
    }
}

// Close modals on overlay click
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.style.display = 'none';
    }
});

// Close modals on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
    }
});
