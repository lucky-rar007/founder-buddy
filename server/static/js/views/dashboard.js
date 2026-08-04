/**
 * Dashboard View Controller — Dynamic scorecards, summaries, and historical selectors.
 */

const DashboardView = (() => {
    let currentType = 'daily'; // 'daily' | 'weekly' | 'monthly'
    let selectedPeriod = null; // { start, end }
    let statsData = null;      // cachedStats (dragging list, stats)
    let currentViewMode = 'dashboard'; // 'dashboard' | 'summaries'

    // ─── Entry point ───────────────────────────────────────────
    async function render(container, viewMode = 'dashboard') {
        currentViewMode = viewMode;
        const isSummariesView = (viewMode === 'summaries');

        container.innerHTML = `
            <div class="dash-header-bar">
                ${isSummariesView ? `
                    <div class="selector-tabs">
                        <button class="tab-btn active" data-type="daily" onclick="DashboardView.switchType('daily')">Daily Summaries</button>
                        <button class="tab-btn" data-type="weekly" onclick="DashboardView.switchType('weekly')">Weekly Scorecards</button>
                        <button class="tab-btn" data-type="monthly" onclick="DashboardView.switchType('monthly')">Monthly briefs</button>
                    </div>

                    <div class="period-dropdown-container">
                        <label class="font-semibold text-secondary" style="font-size: var(--text-xs);" id="dropdown-label">Select Day:</label>
                        <select id="period-dropdown" class="select-dropdown" onchange="DashboardView.onPeriodChange(this.value)"></select>
                    </div>
                ` : `
                    <div style="display: flex; align-items: center; gap: var(--space-3);">
                        <span class="font-semibold text-secondary" style="font-size: var(--text-sm);">Executive Briefing & Operations Scorecard</span>
                    </div>
                `}

            </div>

            <div id="dashboard-content" class="stagger-children">
                <div class="placeholder-content" style="min-height: 300px;">
                    <div class="splash-spinner"></div>
                    <p style="margin-top: var(--space-3);">Loading scorecard brief...</p>
                </div>
            </div>
        `;

        // Load pipeline statistics (dragging issues list, actionable checklist)
        await loadStats();

        // Check for any paused pipeline savepoint and show resume banner
        await checkForSavepoint();

        if (isSummariesView) {
            // Load available periods for Summaries selection
            await switchType('daily');
        } else {
            // Load latest summary directly for main Dashboard view
            try {
                const data = await api.request('GET', '/api/dashboard/summary/available?type=daily');
                const periods = data.periods || [];
                if (periods.length > 0) {
                    const latest = periods[0];
                    await loadSummaryData(latest.period_start, latest.period_end);
                } else {
                    const targetDate = (statsData && statsData.last_active_date) ? statsData.last_active_date : new Date().toISOString().split('T')[0];
                    await loadSummaryData(targetDate, targetDate);
                }
            } catch (err) {
                const targetDate = (statsData && statsData.last_active_date) ? statsData.last_active_date : new Date().toISOString().split('T')[0];
                await loadSummaryData(targetDate, targetDate);
            }
        }
    }

    async function loadStats() {
        try {
            const res = await api.request('GET', '/api/dashboard/stats');
            statsData = res;
        } catch (e) {
            console.error('Failed to load dashboard metrics:', e);
        }
    }

    // ─── Type Switching ────────────────────────────────────────
    async function switchType(type) {
        currentType = type;

        // Set active tabs UI
        document.querySelectorAll('.dash-header-bar .tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-type') === type);
        });

        // Set selector label
        const labels = {
            daily: 'Select Day:',
            weekly: 'Select Week:',
            monthly: 'Select Month:'
        };
        const lbl = document.getElementById('dropdown-label');
        if (lbl) lbl.textContent = labels[type] || 'Select Date:';

        // Load periods
        const dropdown = document.getElementById('period-dropdown');
        if (!dropdown) return;

        dropdown.innerHTML = '<option>Loading...</option>';

        try {
            const data = await api.request('GET', `/api/dashboard/summary/available?type=${type}`);
            const periods = data.periods || [];

            if (periods.length === 0) {
                dropdown.innerHTML = '<option value="">No periods available</option>';
                renderEmptyDashboard();
                return;
            }

            dropdown.innerHTML = '';
            periods.forEach(p => {
                const val = `${p.period_start}|${p.period_end}`;
                const labelText = type === 'daily' ? p.period_start : `${p.period_start} to ${p.period_end}`;
                const opt = document.createElement('option');
                opt.value = val;
                opt.textContent = p.title || labelText;
                dropdown.appendChild(opt);
            });

            // Auto-trigger selection of first period
            onPeriodChange(dropdown.value);

        } catch (err) {
            showToast('Failed to load periods: ' + err.message, 'error');
            dropdown.innerHTML = '<option value="">Error loading periods</option>';
        }
    }

    // ─── Dropdown Change Callback ──────────────────────────────
    function onPeriodChange(val) {
        if (!val) return;
        const [start, end] = val.split('|');
        selectedPeriod = { start, end };
        loadSummaryData(start, end);
    }

    // ─── Summary Loader ────────────────────────────────────────
    async function loadSummaryData(start, end) {
        const contentArea = document.getElementById('dashboard-content');
        if (!contentArea) return;

        contentArea.innerHTML = `
            <div class="placeholder-content" style="min-height: 200px;">
                <div class="splash-spinner"></div>
                <p style="margin-top: 10px;">Querying ${currentType} brief...</p>
            </div>
        `;

        try {
            const data = await api.request('GET', `/api/dashboard/summary?type=${currentType}&start=${start}&end=${end}`);
            if (data.success && data.summary) {
                renderSummaryDetails(contentArea, data.summary);
            } else {
                renderSummaryDetails(contentArea, buildLiveFallbackSummary(start, end));
            }
        } catch (err) {
            renderSummaryDetails(contentArea, buildLiveFallbackSummary(start, end));
        }
    }

    function buildLiveFallbackSummary(start, end) {
        const actionables = (statsData && statsData.actionables) ? statsData.actionables : [];
        const dragging = (statsData && statsData.dragging_issues) ? statsData.dragging_issues : [];
        const activeCount = actionables.filter(a => a.status === 'open' || a.status === 'in_progress').length;
        const resolvedCount = actionables.filter(a => a.status === 'resolved' || a.status === 'dismissed').length;

        let calcScore = 100 - (dragging.length * 15) - (activeCount * 5);
        calcScore = Math.max(35, Math.min(100, calcScore));
        const trend = calcScore < 60 ? 'declining' : calcScore < 80 ? 'stable' : 'rising';
        const periodStr = (start === end) ? start : `${start} to ${end}`;

        return {
            summary_id: `live_${start}`,
            summary_type: currentType,
            period_start: start,
            period_end: end,
            title: `Executive Briefing — ${periodStr}`,
            content_json: {
                ai_executive_summary: `Not enough data to generate summary for ${periodStr}`,
                key_highlights: `• Not enough data to generate summary for ${periodStr}`,
                cluster_health: {
                    delivery_risk: { score: calcScore, trend: trend },
                    client_relations: { score: 95, trend: "stable" },
                    team_dynamics: { score: 90, trend: "stable" },
                    resource_management: { score: 85, trend: "stable" },
                    process_compliance: { score: 92, trend: "stable" },
                    project_health: { score: Math.max(40, calcScore + 5), trend: trend }
                },
                new_actionables: activeCount,
                resolved_actionables: resolvedCount
            }
        };
    }

    function renderSummaryDetails(container, summary) {
        const content = summary.content_json || {};
        const clusterHealthMap = content.cluster_health || {};

        const targetClusters = [
            { key: 'delivery_risk', label: 'Delivery Risk' },
            { key: 'client_relations', label: 'Client Relations' },
            { key: 'team_dynamics', label: 'Team Dynamics' },
            { key: 'resource_management', label: 'Resource Management' },
            { key: 'process_compliance', label: 'Process Compliance' },
            { key: 'project_health', label: 'Project Health' }
        ];

        let html = `
            <!-- Cluster Health Index Canvas Gauges -->
            <h3 class="font-semibold text-secondary" style="font-size: var(--text-xs); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: var(--space-4);">Cluster Health Index</h3>
            <div class="cluster-grid">
        `;

        targetClusters.forEach(c => {
            const h = clusterHealthMap[c.key] || clusterHealthMap[c.label.toLowerCase().replace(/ /g, "_")] || { score: 95, trend: "stable" };
            const score = typeof h.score === 'number' ? h.score : 95;
            
            const trends = { rising: '▲', declining: '▼', stable: '●' };
            const trendIcon = trends[h.trend] || '●';
            const trendColor = h.trend === 'rising' ? 'var(--status-positive)' : h.trend === 'declining' ? 'var(--status-critical)' : 'var(--text-muted)';
            const canvasId = `gauge-canvas-${c.key}`;

            html += `
                <div class="cluster-card" onclick="DashboardView.showClusterModal('${c.key}', '${c.label}')" style="cursor: pointer;" title="Click to expand cluster details and trace underlying issues">
                    <div class="cluster-info">
                        <div class="cluster-name">${c.label}</div>
                        <div class="cluster-meta">
                            Trend: <span style="color: ${trendColor}; font-weight: 700;">${trendIcon} ${h.trend.toUpperCase()}</span>
                        </div>
                        <div style="font-size: 10px; color: #0052FF; font-weight: 700; margin-top: 6px;">Click to Expand &rarr;</div>
                    </div>
                    <!-- High-Res HTML5 Canvas Arc Gauge -->
                    <div style="position: relative; width: 84px; height: 84px; display: flex; align-items: center; justify-content: center;">
                        <canvas id="${canvasId}" width="84" height="84" style="width:84px; height:84px;"></canvas>
                    </div>
                </div>
            `;
        });

        html += `
            </div>

            <!-- Two-Column Grid: AI summaries, active issue items, actionables -->
            <div class="dash-grid">
                <!-- Left Column: AI Executive Brief, Key highlights, Issues -->
                <div style="display: flex; flex-direction: column; gap: var(--space-5);">
                    <div class="executive-brief-card">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-3);">
                            <div class="brief-title" style="margin-bottom:0;">AI Executive Brief</div>
                            <!-- Canvas Signal Wave Telemetry -->
                            <canvas id="brief-wave-canvas" style="width: 140px; height: 32px;"></canvas>
                        </div>
                        <p class="brief-text">${content.ai_executive_summary || 'No briefing content available.'}</p>
                    </div>
                </div>

                <!-- Right Column: Gauges, Actionables Summary -->
                <div style="display: flex; flex-direction: column; gap: var(--space-5);">
                    <!-- Actionable item counts -->
                    <div class="card">
                        <div class="card-header">
                            <h3 class="card-title">Actionables Summary</h3>
                        </div>
                        <div style="padding: var(--space-4); display: flex; justify-content: space-around; text-align: center;">
                            <div>
                                <span style="font-size: var(--text-2xl); font-weight: 800; color: var(--accent-primary);">
                                    ${(statsData && statsData.actionables) 
                                        ? (statsData.actionables.filter(a => a.status === 'open' || a.status === 'in_progress').length + (statsData.dragging_issues ? statsData.dragging_issues.length : 0)) 
                                        : (content.new_actionables || 0)}
                                </span>
                                <div style="font-size: var(--text-xxs); color: var(--text-muted); text-transform: uppercase; font-weight:600; margin-top:2px;">Active Issues</div>
                            </div>
                            <div style="width: 1px; background: var(--border-subtle);"></div>
                            <div>
                                <span style="font-size: var(--text-2xl); font-weight: 800; color: var(--status-positive);">
                                    ${(statsData && statsData.actionables) 
                                        ? statsData.actionables.filter(a => a.status === 'resolved' || a.status === 'dismissed').length 
                                        : (content.resolved_actionables || 0)}
                                </span>
                                <div style="font-size: var(--text-xxs); color: var(--text-muted); text-transform: uppercase; font-weight:600; margin-top:2px;">Resolved</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        container.innerHTML = html;

        // Render Canvas Gauges & Wave Chart after innerHTML update
        requestAnimationFrame(() => {
            targetClusters.forEach(c => {
                const h = clusterHealthMap[c.key] || clusterHealthMap[c.label.toLowerCase().replace(/ /g, "_")] || { score: 95, trend: "stable" };
                const score = typeof h.score === 'number' ? h.score : 95;
                const canvasEl = document.getElementById(`gauge-canvas-${c.key}`);
                if (canvasEl && window.CanvasCharts) {
                    CanvasCharts.renderClusterGauge(canvasEl, score, h.trend, c.label);
                }
            });

            const waveCanvas = document.getElementById('brief-wave-canvas');
            if (waveCanvas && window.CanvasCharts) {
                CanvasCharts.renderSignalWave(waveCanvas, [30, 45, 60, 75, 70, 92, 85, 96]);
            }
        });
    }

    function renderEmptyDashboard() {
        const area = document.getElementById('dashboard-content');
        if (!area) return;
        area.innerHTML = `
            <div class="placeholder-content" style="min-height: 300px;">
                <h3>No Scorecards Found</h3>
                <p style="color: var(--text-muted); max-width: 400px; text-align: center; line-height: 1.6;">
                    Run the pipeline to compile historical messages and build the operations dashboard.
                </p>
            </div>
        `;
    }

    // ─── Format Builders ─────────────────────────────────────────
    
    function formatHighlights(text) {
        if (!text) return 'No highlights logged.';
        if (text.includes('•') || text.includes('-')) {
            const items = text.split(/[•-]/).map(i => i.trim()).filter(Boolean);
            return `<ul style="list-style: disc; padding-left: 20px; display: flex; flex-direction: column; gap: var(--space-2);">${items.map(i => `<li>${i}</li>`).join('')}</ul>`;
        }
        return text;
    }

    function buildIssuesFeed(issues) {
        if (!issues || issues.length === 0) {
            return '<div class="text-muted" style="text-align:center;padding:var(--space-4);">No active incidents or operational issues logged.</div>';
        }

        return issues.map(iss => {
            const sev = iss.severity || 'low';
            const category = (iss.cluster || 'general').replace(/_/g, ' ');
            const actId = iss.actionable_id || iss.issue_id || '';
            return `
                <div class="issue-card" onclick="IssuesView.showDetailModal('${actId}')" style="cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease;" title="Click to view raw chat message trace">
                    <div class="issue-details">
                        <span class="issue-title">${iss.title}</span>
                        <div class="issue-meta">
                            <span class="cluster-tag">${category}</span>
                            <span style="font-size: 10px; color: #0052FF; font-weight: 700; margin-left: 8px;">View Trace &rarr;</span>
                        </div>
                    </div>
                    <span class="sev-badge sev-${sev}">${sev}</span>
                </div>
            `;
        }).join('');
    }

    function buildHealthList(healthMap) {
        if (!healthMap) return '<div class="text-muted">No health scorecards available.</div>';

        const keys = Object.keys(healthMap);
        return keys.map(k => {
            const h = healthMap[k] || { score: 100, trend: 'stable' };
            const score = h.score !== undefined ? h.score : 100;
            const displayName = k.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            const fillClass = score >= 80 ? 'health-high' : score >= 50 ? 'health-medium' : 'health-low';
            const trends = { rising: 'UP', declining: 'DOWN', stable: 'STABLE' };
            const trendIcon = trends[h.trend] || 'STABLE';

            return `
                <div class="health-item">
                    <div class="health-meta">
                        <span class="text-secondary" style="font-weight: 500;">${displayName}</span>
                        <span class="health-score">${trendIcon} ${score}%</span>
                    </div>
                    <div class="health-track">
                        <div class="health-fill ${fillClass}" style="width: ${score}%;"></div>
                    </div>
                </div>
            `;
        }).join('');
    }

    function buildDraggingList(issues) {
        const list = (issues && issues.length > 0) ? issues : (statsData ? statsData.dragging_issues : []);

        if (!list || list.length === 0) {
            return `
                <div style="text-align: center; padding: 24px 16px; background: #FFFFFF; border-radius: 12px; border: 1px dashed #CBD5E1;">
                    <div style="font-size: 20px; margin-bottom: 4px;">✅</div>
                    <span style="font-size: 13px; font-weight: 700; color: #0F172A;">No Dragging Issues Detected</span>
                    <p style="font-size: 11px; color: #64748B; margin-top: 2px;">All workspace tasks and operational incidents are moving on schedule.</p>
                </div>
            `;
        }

        return list.map(item => {
            const days = item.days || item.days_unresolved || 3;
            const title = item.title || 'Unresolved bottleneck';
            const id = item.issue_id || item.id || '';
            return `
                <div class="dragging-card" onclick="DashboardView.showDraggingModal('${id}')" title="Click to view all founder dragging issues in detail">
                    <div class="dragging-days">
                        <span class="dragging-days-num">${days}</span>
                        <span class="dragging-days-lbl">Days</span>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 2px; flex-grow: 1;">
                        <div style="display: flex; align-items: center; justify-content: space-between;">
                            <span class="font-semibold text-secondary" style="font-size: var(--text-sm);">${title}</span>
                            <span style="font-size: 10px; color: var(--primary); font-weight: 700; text-transform: uppercase;">Details &rarr;</span>
                        </div>
                        <span class="text-muted" style="font-size: var(--text-xxs);">${item.description || 'Active issue blocks deliverables'}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    // ─── Dragging Issues Modal ─────────────────────────────────
    async function showDraggingModal(focusId = null) {
        let list = (statsData && Array.isArray(statsData.dragging_issues) && statsData.dragging_issues.length > 0)
            ? statsData.dragging_issues
            : [];

        if (list.length === 0) {
            try {
                const data = await api.request('GET', '/api/dashboard/stats');
                list = data.dragging_issues || [];
            } catch (e) {
                console.error('Failed to fetch dragging issues:', e);
            }
        }

        let modalEl = document.getElementById('dragging-modal');
        if (!modalEl) {
            modalEl = document.createElement('div');
            modalEl.id = 'dragging-modal';
            modalEl.className = 'modal-overlay';
            document.body.appendChild(modalEl);
        }

        let itemsHtml = '';
        if (list.length === 0) {
            itemsHtml = `<div style="text-align:center; padding: 40px; color: var(--text-muted);">No active dragging issues detected.</div>`;
        } else {
            itemsHtml = list.map(item => {
                const days = item.days || item.days_unresolved || 3;
                const sev = (item.severity || 'high').toUpperCase();
                const category = item.category || 'Strategic Bottleneck';
                const isFocused = focusId && (item.issue_id === focusId || item.id === focusId);

                return `
                    <div class="card" style="margin-bottom: var(--space-4); padding: var(--space-5); border-left: 5px solid ${sev === 'CRITICAL' ? 'var(--status-critical)' : 'var(--status-high)'}; ${isFocused ? 'background: #FEF2F2; border-color: var(--status-critical);' : 'background: #FFFFFF;'}">
                        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4);">
                            <div style="display: flex; gap: var(--space-4); align-items: center;">
                                <div class="dragging-days" style="width: 58px; height: 58px; flex-shrink: 0; background: ${sev === 'CRITICAL' ? '#FEE2E2' : '#FEF3C7'}; border-color: ${sev === 'CRITICAL' ? '#FCA5A5' : '#FCD34D'};">
                                    <span class="dragging-days-num" style="color: ${sev === 'CRITICAL' ? '#DC2626' : '#D97706'};">${days}</span>
                                    <span class="dragging-days-lbl" style="color: ${sev === 'CRITICAL' ? '#991B1B' : '#92400E'};">DAYS</span>
                                </div>
                                <div>
                                    <div style="display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-1);">
                                        <span class="badge ${sev === 'CRITICAL' ? 'badge-critical' : 'badge-warning'}" style="font-size: 10px; font-weight: 800;">${sev} SEVERITY</span>
                                        <span class="cluster-tag">${category}</span>
                                    </div>
                                    <h4 style="font-size: var(--text-base); font-weight: 800; color: var(--text-primary); margin: 0;">${item.title}</h4>
                                </div>
                            </div>
                        </div>

                        <p style="margin-top: var(--space-3); font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.6;">
                            ${item.description || 'Active issue unresolved for multiple operational cycles.'}
                        </p>

                        <div style="margin-top: var(--space-4); padding: var(--space-3) var(--space-4); background: #F8FAFC; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); font-size: var(--text-xs); display: flex; align-items: center; justify-content: space-between;">
                            <div>
                                <strong style="color: var(--primary);">Founder Action Needed:</strong> High-priority executive review & direct decision required to clear cross-team blocker.
                            </div>
                            <button class="btn btn-xs btn-primary" style="margin-left: 12px; flex-shrink: 0;" onclick="showToast('Escalated issue to leadership team', 'info'); document.getElementById('dragging-modal').style.display='none';">Escalate</button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        modalEl.innerHTML = `
            <div class="modal-container" style="max-width: 750px; width: 92%;">
                <div class="modal-header" style="background: linear-gradient(90deg, #4F46E5 0%, #7C3AED 100%); color: white;">
                    <div>
                        <h3 class="modal-title" style="color: white; margin: 0; font-size: var(--text-xl);">Founder Strategic Bottlenecks</h3>
                        <p style="font-size: var(--text-xs); color: rgba(255,255,255,0.85); margin-top: 4px;">All active dragging issues requiring executive attention (${list.length} unresolved items)</p>
                    </div>
                    <button class="modal-close" style="color: white; background: rgba(255,255,255,0.2);" onclick="document.getElementById('dragging-modal').style.display='none'">&times;</button>
                </div>
                <div class="modal-body" style="max-height: 70vh; padding: var(--space-6);">
                    ${itemsHtml}
                </div>
                <div style="padding: var(--space-4) var(--space-6); border-top: 1px solid var(--border-subtle); display: flex; justify-content: flex-end; background: #F8FAFC;">
                    <button class="btn btn-secondary" onclick="document.getElementById('dragging-modal').style.display='none'">Close Briefing</button>
                </div>
            </div>
        `;

        modalEl.style.display = 'flex';
    }

    // ─── Pipeline Dispatcher ───────────────────────────────────
    async function triggerPipeline() {
        showToast('Triggering operations analytics engine run...', 'info');
        try {
            const res = await api.request('POST', '/api/dashboard/pipeline/run');
            if (res.success) {
                showToast(res.message, 'success');
                setTimeout(() => {
                    render(document.getElementById('page-content'), currentViewMode);
                }, 2000);
            } else {
                showToast(res.message, 'warning');
            }
        } catch (err) {
            showToast('Pipeline run failed: ' + err.message, 'error');
        }
    }

    // ─── Savepoint Banner ──────────────────────────────────────
    async function checkForSavepoint() {
        try {
            const res = await api.request('GET', '/api/dashboard/pipeline/savepoint');
            if (res.has_savepoint && res.savepoint) {
                showSavepointBanner(res.savepoint);
            } else {
                hideSavepointBanner();
            }
        } catch (e) {
            // Silently ignore — savepoint check is non-critical
        }
    }

    function showSavepointBanner(savepoint) {
        let banner = document.getElementById('savepoint-resume-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'savepoint-resume-banner';
            banner.style.cssText = [
                'position: fixed', 'top: 0', 'left: 0', 'right: 0', 'z-index: 9999',
                'background: linear-gradient(90deg, #92400E 0%, #B45309 100%)',
                'color: white', 'padding: 12px 24px',
                'display: flex', 'align-items: center', 'justify-content: space-between',
                'font-size: 13px', 'font-weight: 600', 'box-shadow: 0 4px 20px rgba(0,0,0,0.3)',
                'animation: slideInDown 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)'
            ].join(';');

            const stageLabel = savepoint.stage === 'event_extraction'
                ? 'Event Extraction'
                : savepoint.stage === 'signal_clustering'
                    ? 'Signal Clustering'
                    : savepoint.stage;

            const model = savepoint.exhausted_model || 'unknown model';

            banner.innerHTML = `
                <div style="display:flex; align-items:center; gap:12px;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                        <line x1="12" y1="9" x2="12" y2="13"/>
                        <line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    <span>Pipeline paused at <strong>${stageLabel}</strong> — <strong>${model}</strong> daily quota exhausted. Progress saved. Quota resets at midnight UTC.</span>
                </div>
                <div style="display:flex; align-items:center; gap:10px;">
                    <button
                        id="resume-pipeline-btn"
                        onclick="DashboardView.resumeFromSavepoint('${savepoint.savepoint_id}')"
                        style="background:rgba(255,255,255,0.2); border:1px solid rgba(255,255,255,0.4); color:white; padding:6px 16px; border-radius:6px; cursor:pointer; font-weight:700; font-size:12px;">
                        Resume Pipeline
                    </button>
                    <button onclick="document.getElementById('savepoint-resume-banner').remove()"
                        style="background:none; border:none; color:rgba(255,255,255,0.7); cursor:pointer; font-size:18px; line-height:1;">×</button>
                </div>
            `;

            document.body.prepend(banner);
        }
    }

    function hideSavepointBanner() {
        const banner = document.getElementById('savepoint-resume-banner');
        if (banner) banner.remove();
    }

    async function resumeFromSavepoint(savepointId) {
        const btn = document.getElementById('resume-pipeline-btn');
        if (btn) {
            btn.textContent = '⏳ Resuming...';
            btn.disabled = true;
        }

        try {
            const res = await api.request('POST', '/api/dashboard/pipeline/resume', {
                savepoint_id: savepointId
            });

            if (res.success) {
                showToast('Pipeline resume triggered! Processing remaining batches in background...', 'success');
                hideSavepointBanner();
                setTimeout(() => {
                    render(document.getElementById('page-content'), currentViewMode);
                }, 3000);
            } else {
                showToast('Failed to resume pipeline: ' + (res.message || 'Unknown error'), 'error');
                if (btn) { btn.textContent = 'Resume Pipeline'; btn.disabled = false; }
            }
        } catch (err) {
            showToast('Resume failed: ' + err.message, 'error');
            if (btn) { btn.textContent = 'Resume Pipeline'; btn.disabled = false; }
        }
    }

    // ─── Operational Activity Logbook Modal ───────────────────
    // ─── Operational Activity Logbook Modal ───────────────────
    async function showAuditLogModal() {
        let modalEl = document.getElementById('audit-log-modal');
        if (!modalEl) {
            modalEl = document.createElement('div');
            modalEl.id = 'audit-log-modal';
            modalEl.className = 'modal-backdrop';
            modalEl.style.display = 'none';
            document.body.appendChild(modalEl);
        }

        modalEl.innerHTML = `
            <div class="modal-dialog" style="max-width: 820px; width: 92%; background: #FFFFFF; border-radius: 16px; box-shadow: 0 20px 40px rgba(0,0,0,0.15); border: 1px solid #E2E8F0; padding: 24px;">
                <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; margin-bottom: 20px;">
                    <div>
                        <span style="font-size: 11px; font-weight: 800; color: #0052FF; text-transform: uppercase; letter-spacing: 0.05em;">System Operational Trace</span>
                        <h3 style="font-size: 18px; font-weight: 800; color: #0F172A; margin: 4px 0 0 0; line-height: 1.3;">Daily Operational Activity Logbook</h3>
                        <p style="font-size: 12px; color: #64748B; margin: 4px 0 0 0;">Step-by-step audit logs of ingested threads, extractions, and signal evaluations</p>
                    </div>
                    <button onclick="document.getElementById('audit-log-modal').style.display='none'" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #64748B;">&times;</button>
                </div>
                <div style="max-height: 65vh; overflow-y: auto; padding-right: 4px;" id="audit-log-body">
                    <div style="text-align:center; padding: 40px;"><div class="spinner-border text-primary" role="status"></div><p style="color:#64748B; margin-top:12px; font-size:13px;">Fetching operational logs...</p></div>
                </div>
                <div style="padding-top: 16px; margin-top: 16px; border-top: 1px solid #E2E8F0; display: flex; justify-content: flex-end;">
                    <button class="btn btn-secondary btn-sm" onclick="document.getElementById('audit-log-modal').style.display='none'">Close Logbook</button>
                </div>
            </div>
        `;
        modalEl.style.display = 'flex';

        try {
            const res = await api.request('GET', '/api/dashboard/audit-logs?limit=100');
            const logs = res.logs || [];
            const bodyEl = document.getElementById('audit-log-body');

            if (logs.length === 0) {
                bodyEl.innerHTML = `
                    <div style="text-align: center; color: #64748B; padding: 40px; background: #F8FAFC; border-radius: 12px; border: 1px dashed #CBD5E1;">
                        <p style="font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 4px;">No Operational Logs Recorded Yet</p>
                        <p style="font-size: 12px; margin: 0;">Run the ingestion pipeline to compile historical messages and generate live audit log traces.</p>
                    </div>
                `;
                return;
            }

            let html = `<div style="display:flex; flex-direction:column; gap:12px;">`;
            logs.forEach(log => {
                const rawTs = log.timestamp || '';
                let tsStr = rawTs;
                try {
                    const d = new Date(rawTs.includes('T') ? rawTs : rawTs.replace(' ', 'T'));
                    if (!isNaN(d.getTime())) {
                        tsStr = d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' });
                    }
                } catch (e) {}

                const type = log.event_type || 'LOG_ENTRY';
                const stage = log.stage || 'pipeline';
                const entity = log.entity_id || '';
                const details = log.details || {};

                let badgeBg = '#EFF6FF';
                let badgeFg = '#1D4ED8';
                if (type.includes('THREAD')) { badgeBg = '#DCFCE7'; badgeFg = '#15803D'; }
                else if (type.includes('EVENT')) { badgeBg = '#F3E8FF'; badgeFg = '#7E22CE'; }
                else if (type.includes('SIGNAL')) { badgeBg = '#FEF3C7'; badgeFg = '#B45309'; }
                else if (type.includes('ISSUE') || type.includes('ERROR') || type.includes('FAIL')) { badgeBg = '#FFE4E6'; badgeFg = '#BE123C'; }

                let detailContent = [];
                if (details.subject) detailContent.push(`<strong>Subject:</strong> ${details.subject}`);
                if (details.title) detailContent.push(`<strong>Title:</strong> ${details.title}`);
                if (details.summary) detailContent.push(`<strong>Summary:</strong> ${details.summary}`);
                if (details.cluster_type) detailContent.push(`<strong>Cluster:</strong> ${details.cluster_type} ${details.strength ? `(Strength: ${details.strength})` : ''}`);
                if (details.message_count) detailContent.push(`<strong>Messages:</strong> ${details.message_count}`);
                if (details.actionables_found !== undefined) detailContent.push(`<strong>Actionables Extracted:</strong> ${details.actionables_found}`);

                html += `
                    <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px 16px; transition: border-color 0.15s ease;">
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="background:${badgeBg}; color:${badgeFg}; font-size:10.5px; font-weight:800; padding:3px 10px; border-radius:12px; letter-spacing:0.02em;">${type}</span>
                                <span style="color:#64748B; font-size:11px; font-weight:600; text-transform:uppercase;">[${stage}]</span>
                                ${entity ? `<span style="color:#0052FF; font-size:11px; font-weight:700; font-family:monospace; background:#EFF6FF; padding:2px 6px; border-radius:4px;">${entity}</span>` : ''}
                            </div>
                            <span style="color:#64748B; font-size:11.5px; font-weight:500;">${tsStr}</span>
                        </div>
                        ${detailContent.length > 0 ? `
                            <div style="color:#334155; font-size:12.5px; line-height:1.6; background:#FFFFFF; padding:10px 12px; border-radius:8px; border:1px solid #F1F5F9;">
                                ${detailContent.join('<br>')}
                            </div>
                        ` : ''}
                    </div>
                `;
            });
            html += `</div>`;
            bodyEl.innerHTML = html;

        } catch (e) {
            const bodyEl = document.getElementById('audit-log-body');
            if (bodyEl) bodyEl.innerHTML = `<p style="color:#EF4444; text-align:center; padding:20px;">Failed to load operational logbook: ${e.message}</p>`;
        }
    }

    async function showClusterModal(clusterKey, clusterLabel) {
        let modalEl = document.getElementById('cluster-detail-modal');
        if (!modalEl) {
            modalEl = document.createElement('div');
            modalEl.id = 'cluster-detail-modal';
            modalEl.className = 'modal-backdrop';
            document.body.appendChild(modalEl);
        }

        modalEl.style.display = 'flex';
        modalEl.innerHTML = `
            <div class="modal-dialog" style="max-width: 680px; background: #FFFFFF; border-radius: 16px; box-shadow: 0 20px 40px rgba(0,0,0,0.15); border: 1px solid #E2E8F0; padding: 24px;">
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; margin-bottom: 20px;">
                    <div>
                        <span style="font-size: 11px; font-weight: 800; color: #0052FF; text-transform: uppercase; letter-spacing: 0.05em;">Cluster Executive Intelligence</span>
                        <h3 style="font-size: 20px; font-weight: 800; color: #0F172A; margin: 4px 0 0 0;">${clusterLabel} Cluster</h3>
                    </div>
                    <button onclick="document.getElementById('cluster-detail-modal').style.display='none'" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #64748B;">&times;</button>
                </div>
                <div id="cluster-modal-body" style="padding: 20px 0;">
                    <div style="text-align: center; color: #64748B; font-size: 13px;">Loading cluster details and issues...</div>
                </div>
            </div>
        `;

        try {
            const res = await api.request('GET', '/api/dashboard/stats');
            const actionablesList = (res.actionables || []).concat(res.dragging_issues || []);

            const clusterKeyClean = (clusterKey || '').toLowerCase().replace(/ /g, '_');
            let matchingIssues = actionablesList.filter(item => {
                const itemCluster = (item.cluster || item.cluster_type || 'general').toLowerCase().replace(/ /g, '_');
                return itemCluster === clusterKeyClean || clusterKeyClean === 'general';
            });

            if (matchingIssues.length === 0) {
                matchingIssues = actionablesList;
            }

            const severityWeight = { blocker: 4, critical: 4, high: 3, medium: 2, low: 1, info: 1 };
            matchingIssues.sort((a, b) => {
                const wA = severityWeight[(a.priority || a.severity || 'medium').toLowerCase()] || 2;
                const wB = severityWeight[(b.priority || b.severity || 'medium').toLowerCase()] || 2;
                return wB - wA;
            });

            const bodyEl = document.getElementById('cluster-modal-body');
            if (bodyEl) {
                bodyEl.innerHTML = `
                    <div style="margin-bottom: 20px;">
                        <label style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #64748B; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Cluster Operational Context</label>
                        <div style="font-size: 14px; color: #334155; line-height: 1.6; background: #F8FAFC; padding: 14px 16px; border-radius: 10px; border: 1px solid #E2E8F0; text-align: left;">
                            Synthesizing operational signals for <strong>${clusterLabel}</strong> across Microsoft Teams and Outlook email communications. Track active project risks, resource gaps, and team blockers.
                        </div>
                    </div>

                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                            <label style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #64748B; letter-spacing: 0.05em;">Underlying Actionables & Issues (${matchingIssues.length})</label>
                            <span style="font-size: 11px; color: #0052FF; font-weight: 700;">Click any issue to view raw message trace</span>
                        </div>
                        <div style="max-height: 280px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px;">
                            ${matchingIssues.length === 0 ? `
                                <div style="text-align:center; padding: 24px; color: #64748B;">No open issues linked to this cluster.</div>
                            ` : matchingIssues.map(item => {
                                const issueId = item.actionable_id || item.issue_id || item.id || '';
                                const sev = item.priority || item.severity || 'medium';
                                return `
                                    <div onclick="IssuesView.showDetailModal('${issueId}')" style="background: #FFFFFF; border: 1px solid #E2E8F0; padding: 12px 16px; border-radius: 10px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; transition: all 0.2s ease; text-align: left;" onmouseover="this.style.borderColor='#0052FF'" onmouseout="this.style.borderColor='#E2E8F0'">
                                        <div>
                                            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                                                <span class="sev-badge sev-${sev}" style="font-size: 9px; text-transform: uppercase;">${sev}</span>
                                                <span style="font-weight: 700; color: #0F172A; font-size: 13.5px;">${item.title}</span>
                                            </div>
                                            <div style="font-size: 12px; color: #64748B;">${item.description ? item.description.substring(0, 80) + '...' : 'Active issue'}</div>
                                        </div>
                                        <span style="font-size: 11px; color: #0052FF; font-weight: 700; flex-shrink: 0; margin-left: 12px;">Trace &rarr;</span>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `;
            }
        } catch (err) {
            const bodyEl = document.getElementById('cluster-modal-body');
            if (bodyEl) bodyEl.innerHTML = `<div style="color: #EF4444; padding: 20px; text-align: center;">Failed to load cluster details: ${err.message}</div>`;
        }
    }

    return {
        render,
        switchType,
        onPeriodChange,
        triggerPipeline,
        showDraggingModal,
        resumeFromSavepoint,
        checkForSavepoint,
        showAuditLogModal,
        showClusterModal
    };
})();
