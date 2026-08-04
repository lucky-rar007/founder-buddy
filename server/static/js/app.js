/**
 * App — SPA bootstrap, routing, and global state.
 *
 * On load:
 * 1. Check onboarding status
 * 2. If not onboarded → render wizard
 * 3. If onboarded → render main app with sidebar
 */

const App = (() => {
    // ─── Initialization ────────────────────────────────────────

    async function init() {
        try {
            const status = await api.getOnboardingStatus();

            // Hide splash screen
            const splash = document.getElementById('splash-screen');
            if (splash) {
                splash.classList.add('hidden');
                setTimeout(() => splash.remove(), 500);
            }

            if (status.completed) {
                const syncStatus = await api.getIngestionStatus();
                if (syncStatus.completed) {
                    showMainView();
                } else {
                    showIngestion();
                }
            } else {
                showOnboarding();
            }
        } catch (err) {
            console.error('Failed to initialize app:', err);

            // Hide splash and show error
            const splash = document.getElementById('splash-screen');
            if (splash) {
                splash.classList.add('hidden');
                setTimeout(() => splash.remove(), 500);
            }

            showToast('Failed to connect to server: ' + err.message, 'error');

            // Show onboarding as fallback
            showOnboarding();
        }
    }

    // ─── View Switching ────────────────────────────────────────

    function showOnboarding() {
        hideView('main-view');
        hideView('ingestion-view');
        const container = document.getElementById('onboarding-view');
        if (container) {
            OnboardingWizard.render(container);
        }
    }

    function showIngestion() {
        hideView('onboarding-view');
        hideView('main-view');
        const container = document.getElementById('ingestion-view');
        if (container) {
            IngestionWizard.render(container);
        }
    }

    async function showMainView() {
        // Strict Guard: Ensure onboarding is completed before entering main view
        try {
            const status = await api.getOnboardingStatus();
            if (!status.completed) {
                showToast('Please complete setup and connect your credentials first.', 'warning');
                showOnboarding();
                return;
            }
        } catch (e) {
            console.error('[App Guard] Failed to verify onboarding status:', e);
        }

        hideView('onboarding-view');
        hideView('ingestion-view');
        const mainView = document.getElementById('main-view');
        if (mainView) {
            mainView.style.display = 'flex';
        }

        // Load org name
        loadOrgName();

        // Set up sidebar navigation
        setupSidebarNav();

        // Show dashboard by default
        navigateTo('dashboard');
    }

    // ─── Sidebar Navigation ────────────────────────────────────

    function setupSidebarNav() {
        const navItems = document.querySelectorAll('.nav-item[data-view]');
        navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const view = item.getAttribute('data-view');
                navigateTo(view);
            });
        });
    }

    function navigateTo(view) {
        // Update active nav item
        const navItems = document.querySelectorAll('.nav-item[data-view]');
        navItems.forEach(item => {
            item.classList.toggle('active', item.getAttribute('data-view') === view);
        });

        // Update page title
        const titles = {
            dashboard: 'Dashboard',
            actionables: 'Actionables Kanban',
            issues: 'Actionables Kanban',
            'dragging-issues': 'Dragging Issues',
            'external-affairs': 'External Affairs',
            summaries: 'Summaries',
            chat: 'Ask Buddy',
            settings: 'Settings',
        };

        const titleEl = document.getElementById('page-title');
        if (titleEl) titleEl.textContent = titles[view] || view;

        // Render view content
        const content = document.getElementById('page-content');
        if (!content) return;

        switch (view) {
            case 'dashboard':
                DashboardView.render(content, 'dashboard');
                break;
            case 'summaries':
                DashboardView.render(content, 'summaries');
                break;
            case 'actionables':
            case 'issues':
                IssuesView.render(content);
                break;
            case 'dragging-issues':
            case 'dragging_issues':
                DraggingIssuesView.render(content);
                break;
            case 'external-affairs':
            case 'external_affairs':
                ExternalAffairsView.render(content);
                break;
            case 'chat':
            case 'chatbot':
                ChatbotView.render(content);
                break;
            case 'settings':
                renderSettingsView(content);
                break;
            default:
                renderPlaceholder(content, '', 'Dashboard', 'Welcome to Founder Buddy.');
        }
    }

    // ─── View Renderers ────────────────────────────────────────

    function renderDashboardPlaceholder(container) {
        container.innerHTML = `
            <div class="stagger-children" style="display: flex; flex-direction: column; gap: var(--space-6);">
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--space-4);">
                    ${buildStatCard('', 'System Status', 'Ready', 'positive')}
                    ${buildStatCard('', 'Data Sources', 'Connected', 'positive')}
                    ${buildStatCard('', 'Ingestion', 'Pending', 'medium')}
                    ${buildStatCard('', 'AI Pipeline', 'Pending', 'medium')}
                </div>

                <div class="card" style="text-align: center; padding: var(--space-12);">
                    <h3 style="font-size: var(--text-xl); font-weight: 700; margin-bottom: var(--space-3);">
                        Setup Complete
                    </h3>
                    <p style="color: var(--text-muted); max-width: 480px; margin: 0 auto; line-height: 1.6;">
                        Your credentials are configured. Select your date range to ingest organizational data from Teams and Outlook.
                    </p>
                </div>
            </div>
        `;
    }

    function renderPlaceholder(container, icon, title, description) {
        container.innerHTML = `
            <div class="placeholder-content" style="min-height: 400px;">
                <h3 style="font-size: var(--text-2xl); font-weight: 800;">${title}</h3>
                <p style="color: var(--text-muted); max-width: 400px; text-align: center; line-height: 1.6;">${description}</p>
            </div>
        `;
    }

    async function renderSettingsView(container) {
        container.innerHTML = `
            <div class="stagger-children" style="display: flex; flex-direction: column; gap: var(--space-5); max-width: 680px;">
                <!-- Encrypted Credentials Card -->
                <div class="card" style="background: #FFFFFF !important; border: 1px solid var(--border) !important;">
                    <div class="card-header" style="background: #FFFFFF !important; border-bottom: 1px solid var(--border) !important; padding: 16px 24px;">
                        <h3 class="card-title" style="color: #0F172A !important; font-size: 16px; font-weight: 700; margin: 0;">Encrypted Credentials & Model Options</h3>
                    </div>
                    <form id="settings-credentials-form" style="padding: 24px; display: flex; flex-direction: column; gap: 18px;">
                        <p style="color: #475569 !important; font-size: 13px; margin-bottom: 4px; line-height: 1.5;">
                            Secrets are encrypted at rest in your local SQLite database using <strong style="color:#0F172A;">Fernet symmetric encryption</strong>. No <span class="font-mono" style="color:var(--accent);">.env</span> file is required.
                        </p>

                        <div class="form-group" style="display:flex; flex-direction:column; gap:6px; margin:0;">
                            <label style="color: #0F172A !important; font-size: 13px; font-weight: 700;">Azure Tenant ID</label>
                            <div class="input-wrapper">
                                <input type="password" id="settings-tenant-id" class="form-control" style="background: #FFFFFF !important; color: #0F172A !important; border: 1px solid var(--border) !important; padding: 10px 14px; border-radius: 6px;" placeholder="Directory Tenant ID (UUID)" required spellcheck="false">
                                <span class="input-toggle" style="color: #475569;" onclick="App.togglePassword('settings-tenant-id', this)">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                                </span>
                            </div>
                        </div>

                        <div class="form-group" style="display:flex; flex-direction:column; gap:6px; margin:0;">
                            <label style="color: #0F172A !important; font-size: 13px; font-weight: 700;">Azure Client ID</label>
                            <div class="input-wrapper">
                                <input type="password" id="settings-client-id" class="form-control" style="background: #FFFFFF !important; color: #0F172A !important; border: 1px solid var(--border) !important; padding: 10px 14px; border-radius: 6px;" placeholder="Application Client ID (UUID)" required spellcheck="false">
                                <span class="input-toggle" style="color: #475569;" onclick="App.togglePassword('settings-client-id', this)">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                                </span>
                            </div>
                        </div>

                        <div class="form-group" style="display:flex; flex-direction:column; gap:6px; margin:0;">
                            <label style="color: #0F172A !important; font-size: 13px; font-weight: 700;">Azure Client Secret</label>
                            <div class="input-wrapper">
                                <input type="password" id="settings-client-secret" class="form-control" style="background: #FFFFFF !important; color: #0F172A !important; border: 1px solid var(--border) !important; padding: 10px 14px; border-radius: 6px;" placeholder="Leave blank to keep current secret">
                                <span class="input-toggle" style="color: #475569;" onclick="App.togglePassword('settings-client-secret', this)">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                                </span>
                            </div>
                            <span style="color: #475569 !important; font-size: 12px;">Status: <span id="settings-secret-status" class="font-mono" style="color: var(--accent) !important; font-weight:700;">••••••••</span></span>
                        </div>

                        <div class="form-group" style="display:flex; flex-direction:column; gap:6px; margin:0;">
                            <label style="color: #0F172A !important; font-size: 13px; font-weight: 700;">Gemini API Key</label>
                            <div class="input-wrapper">
                                <input type="password" id="settings-gemini-key" class="form-control" style="background: #FFFFFF !important; color: #0F172A !important; border: 1px solid var(--border) !important; padding: 10px 14px; border-radius: 6px;" placeholder="Leave blank to keep current API key">
                                <span class="input-toggle" style="color: #475569;" onclick="App.togglePassword('settings-gemini-key', this)">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                                </span>
                            </div>
                            <span style="color: #475569 !important; font-size: 12px;">Status: <span id="settings-key-status" class="font-mono" style="color: var(--accent) !important; font-weight:700;">••••••••</span></span>
                        </div>

                        <div class="form-group" style="display:flex; flex-direction:column; gap:6px; margin:0;">
                            <label style="color: #0F172A !important; font-size: 13px; font-weight: 700;">Primary AI Model</label>
                            <select id="settings-model-name" class="form-control" style="background: #FFFFFF !important; color: #0F172A !important; border: 1px solid var(--border) !important; padding: 10px 14px; border-radius: 6px;">
                                <option value="gemini-3.5-flash-lite">Gemini 3.5 Flash Lite (500 RPD - Recommended)</option>
                                <option value="gemini-3.1-flash-lite">Gemini 3.1 Flash Lite (500 RPD - Lite Fallback)</option>
                                <option value="gemini-3.5-flash">Gemini 3.5 Flash (500 RPD - High Reasoning)</option>
                            </select>
                        </div>

                        <button type="submit" class="btn btn-primary" style="align-self: flex-start; margin-top: 8px; padding: 10px 20px; font-weight: 700;">
                            Save & Encrypt Credentials
                        </button>
                    </form>
                </div>

                <!-- Daily Sync Schedule Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">Daily Sync Schedule</h3>
                    </div>
                    <div style="padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-3);">
                        <p class="text-muted" style="font-size: var(--text-xs); line-height: 1.5;">
                            Configure the preferred time of day when Founder Buddy should automatically run daily incremental data ingestion and build summaries.
                        </p>
                        <form id="settings-schedule-form" style="display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-2);">
                            <div class="form-group" style="margin-bottom:0; flex-grow: 1;">
                                <input type="time" id="settings-sync-time" class="form-control" required style="max-width:180px;">
                            </div>
                            <button type="submit" class="btn btn-primary btn-sm">Save Schedule</button>
                        </form>
                    </div>
                </div>

                <!-- System Diagnostic Actions Card -->
                <div class="card">
                    <div class="card-header">
                        <h3 class="card-title">System & Diagnostic Actions</h3>
                    </div>
                    <div style="padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-4);">
                        <div style="display: flex; flex-direction: column; gap: var(--space-3);">
                            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);">
                                <div>
                                    <span class="font-semibold text-secondary" style="font-size: var(--text-sm);">Run Daily Ingestion</span>
                                    <p class="text-muted" style="font-size: var(--text-xxs); margin-top:2px;">Pull Microsoft Graph data updates manually since last synced date.</p>
                                </div>
                                <button class="btn btn-secondary btn-sm" onclick="App.runManualIngestion()">Sync Now</button>
                            </div>

                            <div style="width: 100%; height: 1px; background: var(--border-subtle);"></div>

                            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);">
                                <div>
                                    <span class="font-semibold text-secondary" style="font-size: var(--text-sm);">Rebuild Dashboard Scorecard</span>
                                    <p class="text-muted" style="font-size: var(--text-xxs); margin-top:2px;">Run event extraction, signals, and summaries compiler pipeline.</p>
                                </div>
                                <button class="btn btn-secondary btn-sm" onclick="DashboardView.triggerPipeline()">Run Pipeline</button>
                            </div>

                            <div style="width: 100%; height: 1px; background: var(--border-subtle);"></div>

                            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);">
                                <div>
                                    <span class="font-semibold text-secondary" style="font-size: var(--text-sm);">Reset Local Database Sync</span>
                                    <p class="text-muted" style="font-size: var(--text-xxs); margin-top:2px;">Clear pipeline events, signals, and scorecards to re-run full extraction.</p>
                                </div>
                                <button class="btn btn-secondary btn-sm text-critical" style="border-color: rgba(220, 38, 38, 0.3);" onclick="App.resetIngestionSync()">Reset Sync</button>
                            </div>

                            <div style="width: 100%; height: 1px; background: var(--border-subtle);"></div>

                            <div style="display: flex; align-items: center; justify-content: space-between; gap: var(--space-4);">
                                <div>
                                    <span class="font-semibold" style="color: #0F172A; font-size: var(--text-sm);">Re-run Setup & Ingestion Wizard</span>
                                    <p class="text-muted" style="font-size: var(--text-xxs); margin-top:2px;">Re-run credentials check, member auto-suggest, and channel exclusion screens.</p>
                                </div>
                                <button class="btn btn-primary btn-sm" onclick="App.reRunOnboardingWizard()">Launch Setup Wizard</button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Danger Zone Card -->
                <div class="card" style="background: rgba(239, 68, 68, 0.05) !important; border: 1.5px solid var(--status-critical-border) !important;">
                    <fieldset style="border: none; padding: var(--space-5); margin: 0;">
                        <legend style="color: var(--status-critical); font-size: var(--text-md); font-weight: 800; font-family: var(--font-display); padding: 0 var(--space-2); display: flex; align-items: center; gap: var(--space-2);">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                            Danger Zone
                        </legend>
                        <div style="display: flex; flex-direction: column; gap: var(--space-4); margin-top: var(--space-3);">
                            <p style="color: var(--text-secondary); font-size: var(--text-xs); line-height: 1.6;">
                                Permanently wipe all encrypted credentials, Azure AD tokens, Gemini API keys, raw message logs, extracted signals, dashboard scorecards, and ChromaDB vector embeddings. 
                                <strong style="color: var(--status-critical);">This action is irreversible.</strong>
                            </p>
                            <button type="button" class="btn btn-danger" style="align-self: flex-start; font-weight: 700;" onclick="App.showSystemResetModal()">
                                Full System Reset & Clean Slate
                            </button>
                        </div>
                    </fieldset>
                </div>
            </div>
        `;

        // Load settings from backend
        try {
            const res = await api.request('GET', '/api/onboarding/settings');
            if (res.success && res.settings) {
                const s = res.settings;
                const tenantInput = document.getElementById('settings-tenant-id');
                const clientInput = document.getElementById('settings-client-id');
                const secretStatus = document.getElementById('settings-secret-status');
                const keyStatus = document.getElementById('settings-key-status');
                const modelSelect = document.getElementById('settings-model-name');

                if (tenantInput) tenantInput.value = s.tenant_id || '';
                if (clientInput) clientInput.value = s.client_id || '';
                if (secretStatus) secretStatus.textContent = s.client_secret_masked || 'Not Configured';
                if (keyStatus) keyStatus.textContent = s.gemini_api_key_masked || 'Not Configured';
                if (modelSelect && s.gemini_model_name) modelSelect.value = s.gemini_model_name;
            }
        } catch (e) {
            console.error('Failed to load settings:', e);
        }

        // Credentials Form Submit Handler
        const form = document.getElementById('settings-credentials-form');
        if (form) {
            form.onsubmit = async (e) => {
                e.preventDefault();
                const tenantId = document.getElementById('settings-tenant-id').value.trim();
                const clientId = document.getElementById('settings-client-id').value.trim();
                const clientSecret = document.getElementById('settings-client-secret').value.trim();
                const geminiKey = document.getElementById('settings-gemini-key').value.trim();
                const modelName = document.getElementById('settings-model-name').value;

                try {
                    const res = await api.request('POST', '/api/onboarding/settings', {
                        tenant_id: tenantId,
                        client_id: clientId,
                        client_secret: clientSecret || null,
                        gemini_api_key: geminiKey || null,
                        gemini_model_name: modelName
                    });

                    if (res.success) {
                        showToast('Credentials updated & encrypted successfully in SQLite!', 'success');
                        setTimeout(() => renderSettingsView(container), 800);
                    } else {
                        showToast('Failed to save settings: ' + res.message, 'error');
                    }
                } catch (err) {
                    showToast('Settings save error: ' + err.message, 'error');
                }
            };
        }
    }

    async function runManualIngestion() {
        showToast('Initiating manual incremental ingestion...', 'info');
        try {
            const res = await api.request('POST', '/api/ingestion/trigger');
            if (res.success) {
                showToast('Incremental ingestion completed successfully.', 'success');
            } else {
                showToast(res.message || 'Ingestion failed.', 'warning');
            }
        } catch (err) {
            showToast('Ingestion sync failed: ' + err.message, 'error');
        }
    }

    async function resetIngestionSync() {
        if (!confirm('Are you sure you want to reset ingestion? This will delete local raw JSON logs and require re-configuring exclusions.')) {
            return;
        }
        showToast('Resetting sync status...', 'info');
        try {
            await api.request('POST', '/api/ingestion/reset');
            showToast('Sync status reset. Redirecting to setup wizard...', 'success');
            setTimeout(() => {
                showIngestion();
            }, 1000);
        } catch (err) {
            showToast('Reset failed: ' + err.message, 'error');
        }
    }

    async function reRunOnboardingWizard() {
        if (!confirm('Re-run Setup Wizard? This will reset the onboarding state so you can configure credentials, user search, and channel exclusions from scratch.')) {
            return;
        }
        showToast('Resetting onboarding state...', 'info');
        try {
            await api.request('POST', '/api/onboarding/reset');
            showToast('Launching Setup Wizard...', 'success');
            setTimeout(() => {
                showOnboarding();
            }, 800);
        } catch (err) {
            showToast('Reset failed: ' + err.message, 'error');
        }
    }

    // ─── UI Helpers ────────────────────────────────────────────

    function buildStatCard(icon, label, value, status) {
        const statusColor = {
            positive: 'var(--status-positive)',
            medium: 'var(--status-medium)',
            critical: 'var(--status-critical)',
            high: 'var(--status-high)',
        }[status] || 'var(--text-secondary)';

        return `
            <div class="card hover-lift" style="padding: var(--space-5);">
                <div style="display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-3);">
                    <span style="font-size: var(--text-xl);">${icon}</span>
                    <span style="font-size: var(--text-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">${label}</span>
                </div>
                <span style="font-size: var(--text-lg); font-weight: 700; color: ${statusColor};">${value}</span>
            </div>
        `;
    }

    function hideView(id) {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    }

    async function loadOrgName() {
        try {
            const result = await api.getOnboardingConfigStatus();
            const badge = document.getElementById('org-name');
            if (badge && result.organization_name) {
                badge.textContent = result.organization_name;
            }
        } catch {
            // Ignore — non-critical
        }
    }

    function togglePassword(inputId, toggleEl) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const eyeIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
        const eyeOffIcon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
        if (input.type === 'password') {
            input.type = 'text';
            toggleEl.innerHTML = eyeOffIcon;
        } else {
            input.type = 'password';
            toggleEl.innerHTML = eyeIcon;
        }
    }

    function showSystemResetModal() {
        const modal = document.getElementById('system-reset-modal');
        const input = document.getElementById('reset-confirm-input');
        const btn = document.getElementById('btn-execute-reset');
        if (modal) {
            if (input) input.value = '';
            if (btn) btn.disabled = true;
            modal.style.display = 'flex';
            modal.classList.remove('hidden');
        }
    }

    function closeSystemResetModal() {
        const modal = document.getElementById('system-reset-modal');
        if (modal) {
            modal.style.display = 'none';
            modal.classList.add('hidden');
        }
    }

    function validateSystemResetInput(inputEl) {
        const btn = document.getElementById('btn-execute-reset');
        if (!btn) return;
        const val = (inputEl.value || '').trim().toUpperCase();
        if (val === 'YES') {
            btn.disabled = false;
            btn.style.opacity = '1';
        } else {
            btn.disabled = true;
            btn.style.opacity = '0.5';
        }
    }

    async function executeSystemReset() {
        const input = document.getElementById('reset-confirm-input');
        const btn = document.getElementById('btn-execute-reset');
        const val = (input ? input.value : '').trim().toUpperCase();

        if (val !== 'YES') {
            showToast("Please type 'YES' to confirm system reset.", 'error');
            return;
        }

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = 'Wiping system...';
        }

        try {
            const res = await api.request('POST', '/api/onboarding/system/reset', { confirmation: 'YES' });
            if (res.success) {
                showToast('System Reset Complete! Returning to setup...', 'success');
                closeSystemResetModal();
                setTimeout(() => {
                    showOnboarding();
                }, 1500);
            } else {
                showToast('System Reset Failed: ' + res.message, 'error');
                if (btn) { btn.disabled = false; btn.innerHTML = 'Wipe Everything & Reset'; }
            }
        } catch (err) {
            showToast('Reset error: ' + err.message, 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = 'Wipe Everything & Reset'; }
        }
    }

    // ─── Public API ────────────────────────────────────────────

    return {
        init,
        showMainView,
        showOnboarding,
        showIngestion,
        navigateTo,
        runManualIngestion,
        resetIngestionSync,
        reRunOnboardingWizard,
        togglePassword,
        showSystemResetModal,
        closeSystemResetModal,
        validateSystemResetInput,
        executeSystemReset
    };
})();


// ─── Global Toast Function ─────────────────────────────────────

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-success)" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
        error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-critical)" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
        warning: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-warning)" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
        info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
        <span class="toast-message">${message}</span>
    `;

    container.appendChild(toast);

    // Auto-remove after 4 seconds
    setTimeout(() => {
        if (toast.parentElement) {
            toast.remove();
        }
    }, 4000);
}


// ─── Bootstrap ─────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    App.init();
});
