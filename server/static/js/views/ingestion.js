/**
 * Ingestion Setup Wizard View.
 *
 * Steps:
 * 1. Range Selection (6 Months, 12 Months, 5 Years, 10 Years, Start)
 * 2. Tree-View Exclusions & Outlook Mail User Selection (with Search & Auto-Suggest)
 * 3. Ingestion Progress & Logs (live sync stream via WebSockets)
 */

const IngestionWizard = (() => {
    let currentStep = 1;
    let selectedRange = '6_months';
    let teamsData = [];
    let usersData = [];
    let selectedOutlookUser = 'me';
    let ws = null;
    let totalSyncedDays = 0;
    let messagesCollected = 0;

    // ─── Help / Guide Content ──────────────────────────────────
    const RANGE_EXPLANATION = `
        <h4>Why choose a range?</h4>
        <p>Founder Buddy performs a full semantic indexing of historic messages. Larger time windows yield richer historic context but take longer to index.</p>
        <ul style="list-style:disc;padding-left:20px;margin:8px 0">
            <li><strong>6 Months:</strong> Best for fast onboarding and focus on current deliverables.</li>
            <li><strong>12 Months:</strong> Standard timeframe capturing the past year's project cycles.</li>
            <li><strong>5/10 Years or Start:</strong> Full archive index. Recommended for established orgs to enable historic lookup.</li>
        </ul>
    `;

    // ─── Entry Point ───────────────────────────────────────────
    function render(container) {
        container.innerHTML = '';
        container.style.display = 'block';

        const wrapper = document.createElement('div');
        wrapper.className = 'onboarding-container';

        const card = document.createElement('div');
        card.className = 'wizard-card';
        card.innerHTML = buildHeader() + buildStepDots() + '<div id="ingest-wizard-body"></div>';

        wrapper.appendChild(card);
        container.appendChild(wrapper);

        renderCurrentStep();
    }

    function buildHeader() {
        const steps = {
            1: { title: 'Select Data Range', subtitle: 'Choose how far back you want Founder Buddy to retrieve and analyze your data.' },
            2: { title: 'Configure Sources & Exclusions', subtitle: 'Select whose Outlook mailbox to integrate and uncheck Teams channels containing noise.' },
            3: { title: 'Stage 1 of 3: Ingesting Workspace Data', subtitle: 'Synchronizing Teams and Outlook historic message logs...' },
        };
        const step = steps[currentStep];
        return `
            <div class="wizard-header">
                ${currentStep === 1 ? `<button class="wizard-help-btn" onclick="IngestionWizard.showHelp()" title="Range guide">?</button>` : ''}
                <div class="wizard-logo">
                    <img src="/static/assets/logo.png" alt="Founder Buddy Logo" width="38" height="38" style="object-fit: contain; border-radius: 8px;">
                    <span class="wizard-logo-text">Founder Buddy</span>
                </div>
                <h2 class="wizard-title" id="wizard-title-el">${step.title}</h2>
                <p class="wizard-subtitle" id="wizard-subtitle-el">${step.subtitle}</p>
            </div>
        `;
    }

    function updateHeaderStage(titleText, subtitleText) {
        const titleEl = document.getElementById('wizard-title-el');
        const subEl = document.getElementById('wizard-subtitle-el');
        if (titleEl && titleText) titleEl.textContent = titleText;
        if (subEl && subtitleText) subEl.textContent = subtitleText;
    }

    function buildStepDots() {
        let html = '<div class="wizard-steps">';
        for (let i = 1; i <= 3; i++) {
            const state = i < currentStep ? 'completed' : i === currentStep ? 'active' : '';
            html += `<div class="step-dot ${state}"></div>`;
            if (i < 3) {
                html += `<div class="step-connector ${i < currentStep ? 'completed' : ''}"></div>`;
            }
        }
        html += '</div>';
        return html;
    }

    function renderCurrentStep() {
        const body = document.getElementById('ingest-wizard-body');
        if (!body) return;

        // Re-render header & step dots
        const card = body.parentElement;
        const header = card.querySelector('.wizard-header');
        const steps = card.querySelector('.wizard-steps');
        if (header) header.outerHTML = buildHeader();
        if (steps) steps.outerHTML = buildStepDots();

        switch (currentStep) {
            case 1: renderStep1(body); break;
            case 2: renderStep2(body); break;
            case 3: renderStep3(body); break;
        }
    }

    // ─── Step 1: Range Selection ───────────────────────────────
    function renderStep1(container) {
        container.innerHTML = `
            <div class="range-grid">
                ${buildRangeCard('6_months', 'Past 6 Months', 'Fast sync. Captures current deliverables and active team discussions.')}
                ${buildRangeCard('12_months', 'Past 12 Months', 'Balanced sync. Indexes a full year of projects, milestones, and emails.')}
                ${buildRangeCard('5_years', 'Past 5 Years', 'Deeper context. Includes older projects, historic client accounts, and archives.')}
                ${buildRangeCard('10_years', 'Past 10 Years', 'Comprehensive sync. Builds a thorough workspace history.')}
                ${buildRangeCard('start', 'Since the Beginning', 'Retrieves the complete historic workspace logs across Teams and Outlook.')}
            </div>

            <div class="wizard-actions">
                <button type="button" class="btn btn-secondary" onclick="IngestionWizard.goToSetup()">
                    ← Back to Setup
                </button>
                <button type="button" class="btn btn-primary btn-lg" onclick="IngestionWizard.nextStep()">
                    Continue →
                </button>
            </div>
        `;
    }

    function buildRangeCard(val, title, desc) {
        const active = selectedRange === val ? 'active' : '';
        return `
            <div class="range-card ${active}" onclick="IngestionWizard.selectRange('${val}')">
                <div class="range-card-radio"></div>
                <div class="range-card-title">${title}</div>
                <div class="range-card-desc">${desc}</div>
            </div>
        `;
    }

    function selectRange(val) {
        selectedRange = val;
        const body = document.getElementById('ingest-wizard-body');
        if (body) renderStep1(body);
    }

    // ─── Step 2: Channel Exclusions & Outlook User Search/Auto-Suggest ─
    async function renderStep2(container) {
        container.innerHTML = `
            <div class="placeholder-content" style="min-height: 200px;">
                <div class="splash-spinner"></div>
                <p style="margin-top: 10px;">Loading organization users, teams and channels...</p>
            </div>
        `;

        try {
            const [teamsRes, usersRes] = await Promise.all([
                api.request('GET', '/api/ingestion/teams'),
                api.request('GET', '/api/ingestion/users')
            ]);

            teamsData = teamsRes.teams || [];
            usersData = usersRes.users || [];

            const teamsWarning = teamsRes.warning || '';
            const warningBanner = teamsWarning ? `
                <div style="background: rgba(245, 158, 11, 0.1); border: 1.5px solid rgba(245, 158, 11, 0.4); border-radius: var(--radius-lg); padding: var(--space-4) var(--space-5); margin-bottom: var(--space-5); font-size: var(--text-xs); color: var(--foreground); line-height: 1.55;">
                    <div style="font-weight: 700; color: #D97706; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                        Azure Permission Warning (HTTP 403 Forbidden)
                    </div>
                    ${teamsWarning}<br>
                    <span style="color: var(--muted-foreground); margin-top: 4px; display: block;">You can still proceed with Outlook Mail integration below!</span>
                </div>
            ` : '';

            container.innerHTML = `
                ${warningBanner}
                <!-- 1. Outlook User Mail Selection (Search & Auto-Suggest) -->
                <div style="background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: var(--space-5); margin-bottom: var(--space-6); box-shadow: var(--shadow-sm);">
                    <label class="form-label" style="font-weight: 700; color: var(--foreground); font-size: var(--text-sm); display: flex; align-items: center; gap: 8px;">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
                        Integrate Outlook Mail Account
                    </label>
                    <p class="text-muted" style="font-size: var(--text-xs); margin-bottom: var(--space-3);">
                        Search and select an organization member by name or email address.
                    </p>

                    <div style="position: relative;" id="user-search-wrapper">
                        <input type="text" id="outlook-user-input" class="form-control"
                               placeholder="Type member name or mail to auto-suggest..."
                               value="${selectedOutlookUser}"
                               oninput="IngestionWizard.handleUserSearchInput(this.value)"
                               onfocus="IngestionWizard.handleUserSearchInput(this.value)"
                               autocomplete="off">
                        <div id="user-autosuggest-dropdown" class="autosuggest-dropdown" style="display: none;"></div>
                    </div>
                </div>

                <!-- 2. Teams Channel Inclusions & Real-Time Search -->
                <div style="margin-bottom: var(--space-3); display: flex; align-items: center; justify-content: space-between;">
                    <span style="font-weight: 700; font-size: var(--text-sm); color: var(--foreground);">
                        Teams Channels to Index
                    </span>
                    <span class="text-muted" style="font-size: var(--text-xs);">
                        Uncheck channels containing chatter or noise
                    </span>
                </div>

                <!-- Teams Search & Auto-Suggest Filter Input -->
                <div style="margin-bottom: var(--space-4); position: relative;">
                    <input type="text" id="teams-search-input" class="form-control"
                           placeholder="Search teams or channels by name..."
                           oninput="IngestionWizard.filterTeamsTree(this.value)"
                           autocomplete="off">
                </div>

                <div class="tree-container" id="teams-tree-container">
                    ${teamsData.length === 0 ? '<p class="text-muted" style="text-align:center;padding:var(--space-6);">No Microsoft Teams found in directory.</p>' : ''}
                    ${teamsData.map(team => buildTeamTreeNode(team)).join('')}
                </div>

                <div class="wizard-actions">
                    <button type="button" class="btn btn-secondary" onclick="IngestionWizard.prevStep()">
                        ← Back
                    </button>
                    <button type="button" class="btn btn-primary btn-lg" onclick="IngestionWizard.saveConfigAndSync()">
                        Start Ingestion →
                    </button>
                </div>
            `;

            // Close user dropdown if clicking outside
            document.addEventListener('click', (e) => {
                const wrapper = document.getElementById('user-search-wrapper');
                const dropdown = document.getElementById('user-autosuggest-dropdown');
                if (wrapper && dropdown && !wrapper.contains(e.target)) {
                    dropdown.style.display = 'none';
                }
            });

        } catch (err) {
            showToast('Failed to load teams/users: ' + err.message, 'error');
            container.innerHTML = `
                <div style="text-align:center;padding:var(--space-6);">
                    <p class="text-critical">Error: ${err.message}</p>
                    <button class="btn btn-secondary btn-sm" style="margin-top:var(--space-4);" onclick="IngestionWizard.renderCurrentStep()">Retry</button>
                </div>
            `;
        }
    }

    // ─── User Search & Auto-Suggest Handler ────────────────────
    function handleUserSearchInput(query) {
        const dropdown = document.getElementById('user-autosuggest-dropdown');
        if (!dropdown) return;

        const q = (query || '').toLowerCase().trim();
        selectedOutlookUser = query;

        // Filter users
        const matches = usersData.filter(u => {
            const name = (u.name || '').toLowerCase();
            const mail = (u.mail || u.userPrincipalName || '').toLowerCase();
            return name.includes(q) || mail.includes(q);
        });

        if (matches.length === 0) {
            dropdown.innerHTML = `<div class="autosuggest-item text-muted" style="pointer-events:none;">Use custom input: "${query || 'me'}"</div>`;
            dropdown.style.display = 'block';
            return;
        }

        let html = '';
        matches.forEach(u => {
            const userMail = u.mail || u.userPrincipalName || u.id;
            html += `
                <div class="autosuggest-item" onclick="IngestionWizard.selectUserMail('${userMail}')">
                    <span style="font-weight: 600;">${u.name}</span>
                    <span style="font-size: 11px; color: #94A3B8;">${userMail}</span>
                </div>
            `;
        });

        dropdown.innerHTML = html;
        dropdown.style.display = 'block';
    }

    function selectUserMail(mail) {
        selectedOutlookUser = mail;
        const input = document.getElementById('outlook-user-input');
        const dropdown = document.getElementById('user-autosuggest-dropdown');
        if (input) input.value = mail;
        if (dropdown) dropdown.style.display = 'none';
    }

    // ─── Teams Search & Live Tree Filtering ────────────────────
    function filterTeamsTree(query) {
        const q = (query || '').toLowerCase().trim();
        const treeContainer = document.getElementById('teams-tree-container');
        if (!treeContainer) return;

        teamsData.forEach(team => {
            const teamNode = document.getElementById(`team-node-${team.id}`);
            const channelsList = document.getElementById(`channels-list-${team.id}`);
            const chevron = teamNode ? teamNode.querySelector('.tree-chevron') : null;

            if (!teamNode) return;

            const teamName = (team.name || '').toLowerCase();
            const teamMatches = teamName.includes(q);

            let matchingChannelCount = 0;
            const channelEls = teamNode.querySelectorAll('.tree-node-channel');

            channelEls.forEach((el, index) => {
                const ch = team.channels[index];
                const chName = ch ? (ch.name || '').toLowerCase() : '';
                
                if (!q || teamMatches || chName.includes(q)) {
                    el.style.display = 'block';
                    matchingChannelCount++;
                } else {
                    el.style.display = 'none';
                }
            });

            if (!q || teamMatches || matchingChannelCount > 0) {
                teamNode.style.display = 'block';
                if (q && (matchingChannelCount > 0 || teamMatches) && channelsList && chevron) {
                    // Expand team node to show matches
                    chevron.classList.remove('collapsed');
                    channelsList.classList.remove('collapsed');
                }
            } else {
                teamNode.style.display = 'none';
            }
        });
    }

    function buildTeamTreeNode(team) {
        return `
            <div class="tree-node-team" id="team-node-${team.id}">
                <div class="tree-team-header">
                    <span class="tree-chevron" onclick="IngestionWizard.toggleChevron('${team.id}')">▼</span>
                    <span class="font-bold">${team.name}</span>
                </div>
                <div class="tree-channels-list" id="channels-list-${team.id}">
                    ${team.channels.map(ch => `
                        <div class="tree-node-channel">
                            <label class="tree-checkbox-label">
                                <input
                                    type="checkbox"
                                    class="custom-chk"
                                    data-team-id="${team.id}"
                                    data-team-name="${team.name}"
                                    data-channel-id="${ch.id}"
                                    data-channel-name="${ch.name}"
                                    checked
                                >
                                <span>#${ch.name}</span>
                            </label>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    function toggleChevron(teamId) {
        const chevron = document.querySelector(`#team-node-${teamId} .tree-chevron`);
        const list = document.getElementById(`channels-list-${teamId}`);
        if (chevron && list) {
            chevron.classList.toggle('collapsed');
            list.classList.toggle('collapsed');
        }
    }

    // ─── Step 3: Ingestion Sync Loader ─────────────────────────
    function renderStep3(container) {
        container.innerHTML = `
            <div class="sync-container">
                <div class="sync-large-percent" id="sync-percent">0.0%</div>
                
                <div class="progress-track">
                    <div class="progress-bar-fill" id="sync-progress-fill" style="width: 0%;"></div>
                </div>

                <div class="sync-status-details">
                    <div>
                        <span class="font-semibold text-secondary">Daily Logs Indexed:</span>
                        <span id="sync-days-count">0 / 0</span>
                    </div>
                    <div>
                        <span class="font-semibold text-secondary">Messages:</span>
                        <span id="sync-msg-count">0</span>
                    </div>
                </div>

                <div class="sync-logger" id="sync-logs">
                    <div class="log-entry info">Establishing secure sync line...</div>
                </div>

                <div id="sync-action-area" style="display: flex; justify-content: center; width: 100%; margin-top: var(--space-4);">
                    <button type="button" id="btn-cancel-sync" class="btn btn-secondary" onclick="IngestionWizard.cancelSync()">
                        Cancel Ingestion
                    </button>
                </div>
            </div>
        `;

        startLiveWebSocketSync();
    }

    // ─── API Setup & Sync Trigger ─────────────────────────────
    async function saveConfigAndSync() {
        const excluded_channels = [];
        const checkboxes = document.querySelectorAll('.custom-chk');

        checkboxes.forEach(chk => {
            if (!chk.checked) {
                excluded_channels.push({
                    team_id: chk.getAttribute('data-team-id'),
                    team_name: chk.getAttribute('data-team-name'),
                    channel_id: chk.getAttribute('data-channel-id'),
                    channel_name: chk.getAttribute('data-channel-name')
                });
            }
        });

        const btn = document.querySelector('.wizard-actions .btn-primary');
        if (btn) {
            btn.classList.add('btn-loading');
            btn.disabled = true;
        }

        const inputUser = document.getElementById('outlook-user-input');
        const userMail = inputUser ? inputUser.value.trim() : (selectedOutlookUser || 'me');

        try {
            await api.request('POST', '/api/ingestion/configure', {
                date_range: selectedRange,
                outlook_user_id: userMail || 'me',
                excluded_channels: excluded_channels
            });

            currentStep = 3;
            renderCurrentStep();
        } catch (err) {
            showToast('Configuration failed: ' + err.message, 'error');
            if (btn) {
                btn.classList.remove('btn-loading');
                btn.disabled = false;
            }
        }
    }

    function startLiveWebSocketSync() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/ingestion/progress`;
        
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            addLog('Sync line connected. Initializing workspace indexing...', 'info');
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleSyncProgressPayload(data);
            } catch (e) {
                console.error('Failed to parse WebSocket payload:', e);
            }
        };

        ws.onerror = (err) => {
            addLog('Sync line error encountered. Re-establishing connection...', 'error');
        };

        ws.onclose = () => {
            addLog('Sync stream closed.', 'info');
        };
    }

    function handleSyncProgressPayload(data) {
        const type = data.type || '';
        const fill = document.getElementById('sync-progress-fill');
        const percentText = document.getElementById('sync-percent');
        const daysCount = document.getElementById('sync-days-count');

        if (type === 'pipeline_start') {
            updateHeaderStage('Stage 2 of 3: AI Event Extraction', 'Analyzing communication threads for key events & actionables...');
            if (percentText) {
                percentText.classList.add('ai-stage');
                percentText.textContent = 'Stage 2 · AI Analysis 0.0%';
            }
            if (fill) fill.style.width = '0%';
            addLog(data.message || 'Starting AI risk signal extraction & thread analysis...', 'info');
        } else if (type === 'pipeline_progress') {
            const rawPercent = data.percent !== undefined ? data.percent : 0;
            const percentVal = Number(rawPercent);
            const percentStr = percentVal.toFixed(1);
            if (fill) fill.style.width = `${percentStr}%`;

            const msgText = (data.message || '').toLowerCase();
            const isClustering = percentVal >= 80 || msgText.includes('cluster') || msgText.includes('health') || msgText.includes('chromadb') || msgText.includes('vector');

            if (isClustering) {
                updateHeaderStage('Stage 3 of 3: Signal Clustering & Health Evaluation', 'Synthesizing executive signals and detecting operational bottlenecks...');
                if (percentText) {
                    percentText.classList.add('ai-stage');
                    percentText.textContent = `Stage 3 · Clustering ${percentStr}%`;
                }
            } else {
                updateHeaderStage('Stage 2 of 3: AI Event Extraction', 'Analyzing communication threads for key events & actionables...');
                if (percentText) {
                    percentText.classList.add('ai-stage');
                    percentText.textContent = `Stage 2 · AI Analysis ${percentStr}%`;
                }
            }

            if (data.message) {
                addLog(data.message, 'info');
            }
        } else if (type === 'sync_start' || type === 'progress_update' || type === 'progress') {
            updateHeaderStage('Stage 1 of 3: Ingesting Workspace Data', 'Synchronizing Teams and Outlook historic message logs...');
            const rawPercent = data.percent !== undefined ? data.percent : (data.percentage || 0);
            const percent = Number(rawPercent).toFixed(1);

            if (fill) fill.style.width = `${percent}%`;
            if (percentText) {
                percentText.classList.remove('ai-stage');
                percentText.textContent = `Stage 1 · Ingestion ${percent}%`;
            }
            if (daysCount && data.total_days !== undefined) {
                daysCount.textContent = `${data.completed_days || 0} / ${data.total_days || 0}`;
            }

            const msgCountEl = document.getElementById('sync-msg-count');
            if (msgCountEl && data.total_messages !== undefined) {
                msgCountEl.textContent = Number(data.total_messages).toLocaleString();
            }

            if (data.log_message) {
                addLog(data.log_message, data.log_type || 'info');
            }
        } else if (type === 'source_start') {
            if (data.source_name) {
                addLog(`Indexing source: ${data.source_name}...`, 'info');
            }
        } else if (type === 'sync_complete' || type === 'completed') {
            updateHeaderStage('Ingestion & Analysis Complete', 'Workspace analysis finished successfully.');
            if (fill) fill.style.width = '100%';
            if (percentText) {
                percentText.classList.remove('ai-stage');
                percentText.textContent = '100.0% Complete';
            }

            addLog('Initial Sync & AI Analysis Completed Successfully!', 'success');
            showToast('Workspace Analysis Complete!', 'success');

            const actionArea = document.getElementById('sync-action-area');
            if (actionArea) {
                actionArea.innerHTML = `
                    <div style="display: flex; flex-direction: column; align-items: center; gap: 12px; margin-top: 8px;">
                        <button type="button" class="btn btn-primary btn-lg" style="padding: 14px 40px; font-size: 16px; font-weight: 800; border-radius: 9999px; box-shadow: 0 0 25px rgba(0, 82, 255, 0.4); animation: pulse 2s infinite;" onclick="App.init()">
                            Launch Executive Dashboard &rarr;
                        </button>
                        <span style="font-size: 12px; color: var(--muted-foreground);">Auto-launching workspace in <strong id="redirect-countdown" style="color: var(--accent); font-weight:700;">10</strong>s...</span>
                    </div>
                `;
            }

            let countdown = 10;
            const timer = setInterval(() => {
                countdown--;
                const timerEl = document.getElementById('redirect-countdown');
                if (timerEl) timerEl.textContent = countdown;
                if (countdown <= 0) {
                    clearInterval(timer);
                    App.init();
                }
            }, 1000);
        } else if (type === 'error') {
            addLog(`Error: ${data.message || 'Ingestion failed'}`, 'error');
            showToast('Ingestion Sync Failed: ' + (data.message || 'Error occurred'), 'error');
        }
    }

    function addLog(msg, type = 'info') {
        const logger = document.getElementById('sync-logs');
        if (!logger) return;

        const entry = document.createElement('div');
        entry.className = `log-entry ${type}`;
        const timestamp = new Date().toLocaleTimeString();
        entry.textContent = `[${timestamp}] ${msg}`;

        logger.appendChild(entry);
        logger.scrollTop = logger.scrollHeight;
    }

    function cancelSync() {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send('cancel');
            addLog('Cancelling ingestion sync request sent...', 'error');
        }
        currentStep = 2;
        renderCurrentStep();
    }

    function prevStep() {
        if (currentStep > 1) {
            currentStep--;
            renderCurrentStep();
        }
    }

    function nextStep() {
        if (currentStep < 3) {
            currentStep++;
            renderCurrentStep();
        }
    }

    function showHelp() {
        const modalBody = document.getElementById('help-modal-body');
        const modalTitle = document.getElementById('help-modal-title');
        const modal = document.getElementById('help-modal');

        if (modalBody && modalTitle && modal) {
            modalTitle.textContent = 'Data Range Guide';
            modalBody.innerHTML = RANGE_EXPLANATION;
            modal.style.display = 'flex';

            const closeBtn = document.getElementById('help-modal-close');
            if (closeBtn) {
                closeBtn.onclick = () => { modal.style.display = 'none'; };
            }
        }
    }

    function goToSetup() {
        App.showOnboarding();
    }

    function goToDashboard() {
        App.showMainView();
    }

    return {
        render,
        selectRange,
        nextStep,
        prevStep,
        goToSetup,
        goToDashboard,
        saveConfigAndSync,
        toggleChevron,
        handleUserSearchInput,
        selectUserMail,
        filterTeamsTree,
        cancelSync,
        showHelp
    };
})();
