/**
 * Actionables View Controller — Interactive Kanban Board with click and drag-and-drop status syncs.
 */

const IssuesView = (() => {
    let actionableList = [];

    // ─── Entry Point ──────────────────────────────────────────
    async function render(container) {
        container.innerHTML = `
            <div class="placeholder-content" style="min-height: 300px;">
                <div class="splash-spinner"></div>
                <p style="margin-top: var(--space-3);">Loading Actionables Kanban...</p>
            </div>
        `;

        try {
            const data = await api.request('GET', '/api/dashboard/stats');
            // Filter Teams actionables for this board (Outlook emails are in External Affairs)
            const allActionables = data.actionables || [];
            actionableList = allActionables.filter(item => item.source !== 'outlook');
            renderBoard(container);
        } catch (e) {
            container.innerHTML = `
                <div class="card" style="text-align:center;padding:var(--space-8);">
                    <p class="text-critical">Failed to load Actionables Kanban: ${e.message}</p>
                </div>
            `;
        }
    }

    // ─── Render Columns ────────────────────────────────────────
    function renderBoard(container) {
        // Group items by status
        const columns = {
            open: [],
            in_progress: [],
            resolved: [],
            dismissed: []
        };

        actionableList.forEach(item => {
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
            <div class="kanban-board">
        `;

        const severityWeight = { blocker: 4, critical: 4, high: 3, medium: 2, low: 1, info: 1 };

        Object.keys(columns).forEach(status => {
            const items = columns[status];
            items.sort((a, b) => {
                const wA = severityWeight[(a.priority || a.severity || 'medium').toLowerCase()] || 2;
                const wB = severityWeight[(b.priority || b.severity || 'medium').toLowerCase()] || 2;
                return wB - wA;
            });
            const col = columnHeaders[status];

            html += `
                <div class="kanban-column" id="col-${status}">
                    <div class="kanban-column-header">
                        <div class="kanban-column-title">
                            <span>${col.icon}</span>
                            <span>${col.label}</span>
                        </div>
                        <span class="kanban-count-badge" id="col-count-${status}">${items.length}</span>
                    </div>
                    <div class="kanban-column-body" id="col-body-${status}" 
                         ondragover="IssuesView.allowDrop(event)" 
                         ondrop="IssuesView.drop(event, '${status}')">
            `;

            if (items.length === 0) {
                html += `<div class="text-muted text-center" style="font-size: var(--text-xs); padding: var(--space-8); border: 1px dashed var(--border-default); border-radius: var(--radius-sm); pointer-events: none;">Drop tasks here</div>`;
            } else {
                items.forEach(item => {
                    const priority = item.priority || 'medium';
                    const sourceText = item.source === 'teams' ? 'Teams' : 'Outlook';
                    const actId = item.actionable_id || item.issue_id || item.id || '';
                    
                    html += `
                        <div class="kanban-card" 
                             draggable="true" 
                             ondragstart="IssuesView.drag(event)" 
                             onclick="IssuesView.showDetailModal('${actId}')"
                             id="act_${actId}"
                             style="cursor: pointer; position: relative;">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 4px;">
                                <div class="kanban-card-title" style="margin-bottom: 0;">${item.title}</div>
                                <div class="card-menu-container" style="position: relative;">
                                    <button class="card-menu-btn" onclick="event.stopPropagation(); IssuesView.toggleCardMenu(event, '${actId}')" title="Card Actions" style="background: none; border: none; font-size: 16px; font-weight: bold; color: #64748B; cursor: pointer; padding: 0 4px; line-height: 1;">&#8942;</button>
                                    <div id="card-menu-${actId}" class="card-menu-dropdown" style="position: absolute; right: 0; top: 22px; background: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.15); z-index: 999; width: 170px; padding: 6px 0; display: none;">
                                        <div style="font-size: 10px; font-weight: 800; color: #64748B; text-transform: uppercase; padding: 4px 12px; letter-spacing: 0.05em;">Edit Severity</div>
                                        <div style="display: flex; gap: 4px; padding: 4px 12px 8px 12px; border-bottom: 1px solid #E2E8F0;">
                                            <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${actId}', 'low')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#F1F5F9; color:#475569;">LOW</button>
                                            <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${actId}', 'medium')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#EFF6FF; color:#0052FF;">MED</button>
                                            <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${actId}', 'high')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#FEF3C7; color:#D97706;">HIGH</button>
                                            <button onclick="event.stopPropagation(); IssuesView.changeSeverity('${actId}', 'critical')" style="flex:1; font-size:9px; font-weight:800; padding:2px 4px; border-radius:4px; border:1px solid #CBD5E1; cursor:pointer; background:#FEE2E2; color:#DC2626;">CRIT</button>
                                        </div>
                                        <div onclick="event.stopPropagation(); IssuesView.updateStatusFromModal('${actId}', 'dismissed')" style="padding: 8px 12px; font-size: 12px; color: #334155; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                                            🚫 Dismiss
                                        </div>
                                        <div onclick="event.stopPropagation(); IssuesView.deleteItem('${actId}')" style="padding: 8px 12px; font-size: 12px; color: #DC2626; font-weight: 700; cursor: pointer; display: flex; align-items: center; gap: 6px; border-top: 1px solid #F1F5F9;">
                                            🗑️ Delete Item
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="kanban-card-desc">
                                ${item.description || 'No description provided.'}
                            </div>
                            <div class="kanban-card-meta">
                                <span class="sev-badge sev-${priority}" style="font-size:9px; padding: 2px 8px;">${priority}</span>
                                <span style="font-size: 11px; color: #0052FF; font-weight: 700;">${sourceText} &bull; View Message Trace &rarr;</span>
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
        if (!id || !id.startsWith("act_")) return;

        const actionableId = id.replace("act_", "");
        const card = document.getElementById(id);
        const colBody = document.getElementById(`col-body-${targetStatus}`);

        if (!card || !colBody) return;

        const placeholder = colBody.querySelector('.text-center');
        if (placeholder) placeholder.remove();

        colBody.appendChild(card);
        updateColumnCounts();

        try {
            await api.request('POST', '/api/dashboard/actionable/status', {
                actionable_id: actionableId,
                status: targetStatus
            });
            showToast(`Task status updated to ${targetStatus.toUpperCase()}`, 'success');
        } catch (err) {
            showToast('Failed to save task status: ' + err.message, 'error');
            render(document.getElementById('page-content'));
        }
    }

    function updateColumnCounts() {
        ['open', 'in_progress', 'resolved', 'dismissed'].forEach(status => {
            const colBody = document.getElementById(`col-body-${status}`);
            const countBadge = document.getElementById(`col-count-${status}`);
            if (colBody && countBadge) {
                const count = colBody.querySelectorAll('.kanban-card').length;
                countBadge.textContent = count;
                
                if (count === 0 && !colBody.querySelector('.text-center')) {
                    colBody.innerHTML = `<div class="text-muted text-center" style="font-size: var(--text-xxs); padding: var(--space-8); border: 1px dashed var(--border-subtle); border-radius: var(--radius-sm); pointer-events: none;">Drop tasks here</div>`;
                }
            }
        });
    }

    function closeDetailModal() {
        const modalEl = document.getElementById('issue-trace-modal');
        if (modalEl) {
            modalEl.style.display = 'none';
            modalEl.classList.add('hidden');
        }
    }

    // ─── Interactive Issue Trace & Detail Modal ────────────────
    async function showDetailModal(actionableId) {
        let modalEl = document.getElementById('issue-trace-modal');
        if (!modalEl) {
            modalEl = document.createElement('div');
            modalEl.id = 'issue-trace-modal';
            modalEl.className = 'modal-backdrop';
            document.body.appendChild(modalEl);
        }

        modalEl.style.zIndex = '100010';
        modalEl.classList.remove('hidden');
        modalEl.style.display = 'flex';
        modalEl.innerHTML = `
            <div class="modal-dialog" style="max-width: 640px; background: #FFFFFF; border-radius: 16px; box-shadow: 0 20px 40px rgba(0,0,0,0.15); border: 1px solid #E2E8F0; padding: 24px;">
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; margin-bottom: 20px;">
                    <div style="font-size: 14px; font-weight: 800; color: #0052FF; text-transform: uppercase; letter-spacing: 0.05em;">Issue Communication Trace</div>
                    <button onclick="IssuesView.closeDetailModal()" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #64748B;">&times;</button>
                </div>
                <div style="display: flex; align-items: center; justify-content: center; padding: 40px;">
                    <div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading trace...</span></div>
                </div>
            </div>
        `;

        try {
            const data = await api.request('GET', `/api/dashboard/actionable/trace/${actionableId}`);
            const act = data.actionable || {};
            const thread = data.thread || {};
            const messages = data.messages || [];

            const sourceName = act.source === 'teams' ? 'Microsoft Teams' : 'Outlook Email';
            const threadTitle = thread.subject || thread.channel_name || 'Ingested Message Thread';
            const channelContext = thread.team_name && thread.channel_name ? `${thread.team_name} > ${thread.channel_name}` : (thread.subject || 'General Channel');
            const participants = thread.participants || 'Team Members';

            const getInitials = (name) => {
                if (!name) return '?';
                const parts = name.trim().split(' ').filter(Boolean);
                if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
                return name.substring(0, 2).toUpperCase();
            };

            const getAvatarColor = (name) => {
                const colors = ['#0052FF', '#0D9488', '#7C3AED', '#D97706', '#E11D48', '#2563EB', '#059669'];
                let hash = 0;
                for (let i = 0; i < (name || '').length; i++) {
                    hash = name.charCodeAt(i) + ((hash << 5) - hash);
                }
                return colors[Math.abs(hash) % colors.length];
            };

            const formatMessageDate = (ts) => {
                if (!ts) return '';
                try {
                    const cleanTs = ts.includes('T') ? ts : ts.replace(' ', 'T');
                    const d = new Date(cleanTs);
                    if (isNaN(d.getTime())) return ts;
                    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
                } catch (e) {
                    return ts;
                }
            };

            let chatMessagesHtml = '';
            if (messages.length > 0) {
                chatMessagesHtml = messages.map(msg => {
                    const sender = msg.sender || 'Participant';
                    const initials = getInitials(sender);
                    const avatarColor = getAvatarColor(sender);
                    const dateStr = formatMessageDate(msg.timestamp);

                    return `
                        <div class="chat-msg-row">
                            <div class="chat-msg-avatar" style="background: ${avatarColor};">
                                ${initials}
                            </div>
                            <div class="chat-msg-content">
                                <div class="chat-msg-header">
                                    <span class="chat-sender-name">${sender}</span>
                                    ${dateStr ? `<span class="chat-msg-date">${dateStr}</span>` : ''}
                                </div>
                                <div class="chat-msg-bubble">
                                    ${msg.text}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            } else {
                chatMessagesHtml = `
                    <div style="text-align: center; color: #64748B; padding: 20px; font-size: 13px;">
                        No direct chat messages recorded for this trace.
                    </div>
                `;
            }

            modalEl.innerHTML = `
                <div class="modal-dialog" style="max-width: 680px; background: #FFFFFF; border-radius: 16px; box-shadow: 0 20px 40px rgba(0,0,0,0.15); border: 1px solid #E2E8F0; padding: 24px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; margin-bottom: 20px;">
                        <div>
                            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                <span class="sev-badge sev-${act.priority || 'medium'}">${act.priority || 'medium'}</span>
                                <span style="font-size: 12px; color: #64748B; font-weight: 600;">Source: ${sourceName}</span>
                            </div>
                            <h3 style="font-size: 18px; font-weight: 800; color: #0F172A; margin: 0; line-height: 1.4;">${act.title}</h3>
                        </div>
                        <button onclick="IssuesView.closeDetailModal()" style="background: none; border: none; font-size: 24px; cursor: pointer; color: #64748B;">&times;</button>
                    </div>

                    <!-- Issue Description -->
                    <div style="margin-bottom: 20px;">
                        <label style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #64748B; letter-spacing: 0.05em; display: block; margin-bottom: 6px;">Executive Description</label>
                        <div style="font-size: 14px; color: #334155; line-height: 1.6; background: #F8FAFC; padding: 14px 16px; border-radius: 10px; border: 1px solid #E2E8F0;">
                            ${act.description || 'No detailed description available.'}
                        </div>
                    </div>

                    <!-- Manual Status Picker -->
                    <div style="margin-bottom: 20px;">
                        <label style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #64748B; letter-spacing: 0.05em; display: block; margin-bottom: 8px;">Manually Change State</label>
                        <div style="display: flex; gap: 10px;">
                            ${['open', 'in_progress', 'resolved', 'dismissed'].map(st => `
                                <button onclick="IssuesView.updateStatusFromModal('${act.actionable_id}', '${st}')" 
                                        style="flex: 1; padding: 8px 12px; font-size: 12px; font-weight: 700; border-radius: 8px; cursor: pointer; border: 1px solid ${act.status === st ? '#0052FF' : '#CBD5E1'}; background: ${act.status === st ? '#EFF6FF' : '#FFFFFF'}; color: ${act.status === st ? '#0052FF' : '#475569'}; transition: all 0.2s ease;">
                                    ${st.replace('_', ' ').toUpperCase()}
                                </button>
                            `).join('')}
                        </div>
                    </div>

                    <!-- Traceability Chat Thread Box -->
                    <div style="margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <label style="font-size: 11px; text-transform: uppercase; font-weight: 800; color: #0052FF; letter-spacing: 0.05em;">Source Communication Trace</label>
                            <span style="font-size: 11px; color: #64748B; font-weight: 600;">Context: ${channelContext}</span>
                        </div>
                        <div style="font-size: 11px; color: #64748B; margin-bottom: 8px; font-weight: 500;">
                            Participants: <span style="color: #0F172A; font-weight: 600;">${participants}</span>
                        </div>
                        <div class="chat-trace-wrapper">
                            ${chatMessagesHtml}
                        </div>
                    </div>
                </div>
            `;
        } catch (e) {
            console.error('Failed to load actionable trace:', e);
            modalEl.innerHTML = `
                <div class="modal-dialog" style="max-width: 500px; background: #FFFFFF; border-radius: 16px; padding: 24px;">
                    <h4 style="color: #EF4444; margin-top: 0;">Error Loading Trace</h4>
                    <p style="color: #64748B; font-size: 14px;">${e.message}</p>
                    <button onclick="IssuesView.closeDetailModal()" class="btn btn-primary btn-sm">Close</button>
                </div>
            `;
        }
    }

    async function updateStatusFromModal(actionableId, newStatus) {
        try {
            await api.request('POST', '/api/dashboard/actionable/status', {
                actionable_id: actionableId,
                status: newStatus
            });
            showToast(`Status updated to ${newStatus.toUpperCase()}`, 'success');
            closeDetailModal();
            render(document.getElementById('page-content'));
        } catch (err) {
            showToast('Failed to update status: ' + err.message, 'error');
        }
    }

    function toggleCardMenu(e, actId) {
        if (e) e.stopPropagation();
        document.querySelectorAll('.card-menu-dropdown').forEach(el => {
            if (el.id !== `card-menu-${actId}`) el.style.display = 'none';
        });
        document.querySelectorAll('.kanban-card').forEach(card => card.classList.remove('menu-open'));
        document.querySelectorAll('.card').forEach(card => card.classList.remove('menu-open'));

        const targetMenu = document.getElementById(`card-menu-${actId}`);
        if (targetMenu) {
            const isShowing = (targetMenu.style.display === 'none' || !targetMenu.style.display);
            targetMenu.style.display = isShowing ? 'block' : 'none';
            const parentCard = targetMenu.closest('.kanban-card') || targetMenu.closest('.card');
            if (parentCard && isShowing) {
                parentCard.classList.add('menu-open');
            }
        }
    }

    document.addEventListener('click', () => {
        document.querySelectorAll('.card-menu-dropdown').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.kanban-card').forEach(card => card.classList.remove('menu-open'));
        document.querySelectorAll('.card').forEach(card => card.classList.remove('menu-open'));
    });

    async function changeSeverity(actionableId, newSeverity) {
        try {
            await api.request('POST', '/api/dashboard/actionable/severity', {
                actionable_id: actionableId,
                severity: newSeverity
            });
            showToast(`Severity updated to ${newSeverity.toUpperCase()}`, 'success');
            render(document.getElementById('page-content'));
        } catch (err) {
            showToast('Failed to change severity: ' + err.message, 'error');
        }
    }

    async function deleteItem(actionableId) {
        if (!confirm('Are you sure you want to permanently delete this item?')) return;
        try {
            await api.request('POST', '/api/dashboard/actionable/delete', {
                actionable_id: actionableId
            });
            showToast('Item deleted successfully', 'success');
            render(document.getElementById('page-content'));
        } catch (err) {
            showToast('Failed to delete item: ' + err.message, 'error');
        }
    }

    return {
        render,
        drag,
        allowDrop,
        drop,
        showDetailModal,
        closeDetailModal,
        updateStatusFromModal,
        toggleCardMenu,
        changeSeverity,
        deleteItem
    };
})();
