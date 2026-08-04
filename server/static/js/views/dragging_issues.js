/**
 * Dragging Issues View Controller.
 * Renders operational issues and tasks that have been unresolved over multiple days.
 */

const DraggingIssuesView = (() => {
    let containerEl = null;

    async function render(container) {
        containerEl = container;
        container.innerHTML = `
            <div style="padding: var(--space-6); max-width: 1200px; margin: 0 auto;">
                <!-- Header -->
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px;">
                    <div>
                        <span style="font-size: 11px; font-weight: 800; color: #EF4444; text-transform: uppercase; letter-spacing: 0.05em;">Operational Blockers</span>
                        <h2 style="font-size: 24px; font-weight: 800; color: #0F172A; margin: 4px 0 0 0; letter-spacing: -0.02em;">Dragging Issues</h2>
                        <p style="font-size: 13px; color: #64748B; margin-top: 4px;">Tasks and operational incidents persisting across multiple days without resolution</p>
                    </div>
                </div>

                <!-- Main Content List -->
                <div id="dragging-issues-content">
                    <div style="text-align: center; padding: 40px;">
                        <div class="spinner-border text-primary" role="status"></div>
                        <p style="color: #64748B; margin-top: 12px; font-size: 13px;">Loading unresolved dragging issues...</p>
                    </div>
                </div>
            </div>
        `;

        await loadDraggingIssues();
    }

    async function loadDraggingIssues() {
        const contentEl = document.getElementById('dragging-issues-content');
        if (!contentEl) return;

        try {
            const data = await api.request('GET', '/api/dashboard/stats');
            const dragging = Array.isArray(data.dragging_issues) ? data.dragging_issues : (Array.isArray(data.stats?.dragging_issues) ? data.stats.dragging_issues : []);

            const severityWeight = { blocker: 4, critical: 4, high: 3, medium: 2, low: 1, info: 1 };
            dragging.sort((a, b) => {
                const wA = severityWeight[(a.severity || a.priority || 'medium').toLowerCase()] || 2;
                const wB = severityWeight[(b.severity || b.priority || 'medium').toLowerCase()] || 2;
                return wB - wA;
            });

            if (dragging.length === 0) {
                contentEl.innerHTML = `
                    <div style="text-align: center; color: #64748B; padding: 60px 20px; background: #FFFFFF; border-radius: 16px; border: 1px dashed #CBD5E1;">
                        <div style="font-size: 32px; margin-bottom: 12px;">✅</div>
                        <h3 style="font-size: 16px; font-weight: 700; color: #0F172A; margin-bottom: 6px;">No Dragging Issues Found</h3>
                        <p style="font-size: 13px; color: #64748B; max-width: 440px; margin: 0 auto; line-height: 1.5;">
                            All operational tasks and workspace incidents are currently resolved or moving on schedule.
                        </p>
                    </div>
                `;
                return;
            }

            contentEl.innerHTML = `
                <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px;">
                    ${dragging.map(issue => {
                        const days = issue.days_unresolved || issue.days || 1;
                        const sev = issue.severity || issue.priority || 'high';
                        const issueId = issue.issue_id || issue.actionable_id || issue.id || '';
                        const dateStr = issue.first_detected_at ? new Date(issue.first_detected_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';

                        return `
                            <div class="card hover-lift" 
                                 onclick="IssuesView.showDetailModal('${issueId}')" 
                                 style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px; padding: 18px; cursor: pointer; display: flex; flex-direction: column; justify-content: space-between; transition: all 0.2s ease; position: relative;"
                                 onmouseover="this.style.borderColor='#0052FF'; this.style.boxShadow='0 8px 24px rgba(0,82,255,0.08)';"
                                 onmouseout="this.style.borderColor='#E2E8F0'; this.style.boxShadow='none';">
                                <div>
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                                        <div style="display: flex; align-items: center; gap: 8px;">
                                            <span class="sev-badge sev-${sev}">${sev}</span>
                                            <span style="font-size: 11px; font-weight: 800; color: #EF4444; background: #FFE4E6; padding: 2px 8px; border-radius: 12px;">
                                                ${days} Day${days > 1 ? 's' : ''} Dragging
                                            </span>
                                        </div>
                                        <div class="card-menu-container" style="position: relative;">
                                            <button class="card-menu-btn" onclick="event.stopPropagation(); IssuesView.toggleCardMenu(event, '${issueId}')" title="Card Actions" style="background: none; border: none; font-size: 16px; font-weight: bold; color: #64748B; cursor: pointer; padding: 0 4px; line-height: 1;">&#8942;</button>
                                            <div id="card-menu-${issueId}" class="card-menu-dropdown" style="position: absolute; right: 0; top: 22px; background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.15); z-index: 999; width: 170px; padding: 6px 0; display: none;">
                                                <div style="font-size: 10px; font-weight: 800; color: #64748B; text-transform: uppercase; padding: 4px 12px; letter-spacing: 0.05em;">Edit Severity</div>
                                                <div style="display: flex; gap: 4px; padding: 4px 12px 8px 12px; border-bottom: 1px solid #E2E8F0;">
                                                    <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${issueId}', 'low')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#F1F5F9; color:#475569;">LOW</button>
                                                    <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${issueId}', 'medium')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#EFF6FF; color:#0052FF;">MED</button>
                                                    <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${issueId}', 'high')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#FEF3C7; color:#D97706;">HIGH</button>
                                                    <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${issueId}', 'critical')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#FEE2E2; color:#DC2626;">CRIT</button>
                                                </div>
                                                <div onclick="event.stopPropagation(); IssuesView.updateStatusFromModal('${issueId}', 'dismissed')" style="padding: 8px 12px; font-size: 12px; color: #334155; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                                                    🚫 Dismiss
                                                </div>
                                                <div onclick="event.stopPropagation(); IssuesView.deleteItem('${issueId}')" style="padding: 8px 12px; font-size: 12px; color: #DC2626; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; border-top: 1px solid #F1F5F9;">
                                                    🗑️ Delete Item
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <h4 style="font-size: 15px; font-weight: 700; color: #0F172A; margin: 0 0 8px 0; line-height: 1.4;">
                                        ${issue.title}
                                    </h4>
                                    <p style="font-size: 13px; color: #475569; line-height: 1.5; margin: 0 0 16px 0; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;">
                                        ${issue.description || 'Actionable task persisting across multiple ingestion periods without closure.'}
                                    </p>
                                </div>
                                <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #F1F5F9; padding-top: 12px; font-size: 11px; color: #64748B;">
                                    <span>${dateStr ? `Detected: ${dateStr}` : 'Persisting Blocker'}</span>
                                    <span style="color: #0052FF; font-weight: 700;">View Message Trace &rarr;</span>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        } catch (e) {
            contentEl.innerHTML = `
                <div style="text-align: center; color: #EF4444; padding: 30px;">
                    Failed to load dragging issues: ${e.message}
                </div>
            `;
        }
    }

    return {
        render
    };
})();
