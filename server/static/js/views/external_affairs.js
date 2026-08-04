/**
 * External Affairs View Controller — Interactive Kanban Board for Outlook Emails requiring Founder Attention.
 */

const ExternalAffairsView = (() => {
    let emailActionableList = [];

    // ─── Entry Point ──────────────────────────────────────────
    async function render(container) {
        container.innerHTML = `
            <div class="placeholder-content" style="min-height: 300px;">
                <div class="splash-spinner"></div>
                <p style="margin-top: var(--space-3);">Loading External Affairs board...</p>
            </div>
        `;

        try {
            const data = await api.request('GET', '/api/dashboard/stats');
            const allActionables = data.actionables || [];
            // Filter strictly for Outlook email items requiring attention
            emailActionableList = allActionables.filter(item => item.source === 'outlook');
            renderBoard(container);
        } catch (e) {
            container.innerHTML = `
                <div class="card" style="text-align:center;padding:var(--space-8);">
                    <p class="text-critical">Failed to load External Affairs board: ${e.message}</p>
                </div>
            `;
        }
    }

    // ─── Render Columns ────────────────────────────────────────
    function renderBoard(container) {
        const columns = {
            open: [],
            in_progress: [],
            resolved: [],
            dismissed: []
        };

        emailActionableList.forEach(item => {
            const status = item.status || 'open';
            if (columns[status]) {
                columns[status].push(item);
            } else {
                columns['open'].push(item);
            }
        });

        const columnHeaders = {
            open: { label: 'Open', icon: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>` },
            in_progress: { label: 'In Progress', icon: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>` },
            resolved: { label: 'Resolved', icon: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>` },
            dismissed: { label: 'Dismissed', icon: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/></svg>` }
        };

        let html = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-6); padding: var(--space-5) var(--space-6); background: #FFFFFF !important; border: 1px solid var(--border) !important; border-left: 4px solid var(--accent) !important; border-radius: var(--radius-xl); box-shadow: var(--shadow-sm);">
                <div style="display: flex; align-items: center; gap: var(--space-3);">
                    <div>
                        <strong style="color: #0F172A; font-size: var(--text-sm);">External Affairs Inbox:</strong>
                        <span style="color: #475569; font-size: var(--text-xs); margin-left: 6px;">Client communications & email actionables requiring Founder review.</span>
                    </div>
                </div>
                <span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38BDF8; border: 1px solid rgba(56, 189, 248, 0.3); font-weight: 600;">
                    ${emailActionableList.length} Emails Pending
                </span>
            </div>
            <div class="kanban-board">
        `;

        Object.keys(columns).forEach(status => {
            const items = columns[status];
            const col = columnHeaders[status];

            html += `
                <div class="kanban-column" id="ext-col-${status}">
                    <div class="kanban-column-header">
                        <div class="kanban-column-title">
                            <span>${col.icon}</span>
                            <span>${col.label}</span>
                        </div>
                        <span class="kanban-count-badge" id="ext-col-count-${status}">${items.length}</span>
                    </div>
                    <div class="kanban-column-body" id="ext-col-body-${status}" 
                         ondragover="ExternalAffairsView.allowDrop(event)" 
                         ondrop="ExternalAffairsView.drop(event, '${status}')">
            `;

            if (items.length === 0) {
                html += `<div class="text-muted text-center" style="font-size: var(--text-xs); padding: var(--space-8); border: 1px dashed var(--border-default); border-radius: var(--radius-sm); pointer-events: none;">No emails in ${col.label.toLowerCase()}</div>`;
            } else {
                items.forEach(item => {
                    const priority = item.priority || 'medium';
                    
                    html += `
                        <div class="kanban-card" 
                             draggable="true" 
                             ondragstart="ExternalAffairsView.drag(event)" 
                             id="ext_act_${item.actionable_id}">
                            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#38BDF8" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                                <span style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; color: #38BDF8; font-weight: 600;">Outlook Email</span>
                            </div>
                            <div class="kanban-card-title">${item.title}</div>
                            <div style="font-size: 11px; color: var(--text-muted); margin-bottom: var(--space-3); line-height: 1.4;">
                                ${item.description || 'No description provided.'}
                            </div>
                            <div class="kanban-card-meta">
                                <span class="sev-badge sev-${priority}" style="font-size:9px; padding: 2px 8px;">${priority}</span>
                                <span style="color: var(--text-secondary); font-size: 10px;">${item.created_at ? item.created_at.substring(0, 10) : ''}</span>
                            </div>
                        </div>
                    `;
                });
            }

            html += `
                    </div>
                </div>
            `;
        });

        html += `</div>`;
        container.innerHTML = html;
    }

    // ─── Drag & Drop Handlers ──────────────────────────────────

    function drag(e) {
        e.dataTransfer.setData("text/plain", e.target.id);
        e.dataTransfer.effectAllowed = "move";
    }

    function allowDrop(e) {
        e.preventDefault();
    }

    async function drop(e, targetStatus) {
        e.preventDefault();
        const id = e.dataTransfer.getData("text/plain");
        if (!id || !id.startsWith("ext_act_")) return;

        const actionableId = id.replace("ext_act_", "");
        const card = document.getElementById(id);
        const colBody = document.getElementById(`ext-col-body-${targetStatus}`);

        if (!card || !colBody) return;

        // Visual feedback
        const placeholder = colBody.querySelector('.text-center');
        if (placeholder) placeholder.remove();

        colBody.appendChild(card);

        // API Call
        try {
            await api.request('POST', '/api/dashboard/actionable/status', {
                actionable_id: actionableId,
                status: targetStatus
            });

            const itemIndex = emailActionableList.findIndex(x => x.actionable_id === actionableId);
            if (itemIndex > -1) {
                emailActionableList[itemIndex].status = targetStatus;
            }

            updateCounts();
            app.showToast(`Email status updated to ${targetStatus.replace('_', ' ')}`, 'success');
        } catch (err) {
            app.showToast(`Failed to update status: ${err.message}`, 'error');
            // Re-render board on error
            const container = document.getElementById('page-content');
            if (container) renderBoard(container);
        }
    }

    function updateCounts() {
        const counts = { open: 0, in_progress: 0, resolved: 0, dismissed: 0 };
        emailActionableList.forEach(item => {
            const st = item.status || 'open';
            if (counts[st] !== undefined) counts[st]++;
            else counts.open++;
        });

        Object.keys(counts).forEach(st => {
            const badge = document.getElementById(`ext-col-count-${st}`);
            if (badge) badge.textContent = counts[st];
        });
    }

    return {
        render,
        drag,
        allowDrop,
        drop
    };
})();
