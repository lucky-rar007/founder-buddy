/**
 * Onboarding Wizard — Multi-step setup flow.
 *
 * Steps:
 * 1. Azure credentials (Tenant ID, Client ID, Client Secret)
 * 2. Gemini API key
 * 3. Connection testing
 * 4. Success / complete
 */

const OnboardingWizard = (() => {
    let currentStep = 1;
    const TOTAL_STEPS = 3;

    // ─── Help Content ──────────────────────────────────────────

    const AZURE_HELP = `
        <h4>How to find your Azure credentials</h4>
        <ol>
            <li>Go to <code>portal.azure.com</code> and sign in</li>
            <li>Search for <strong>"App registrations"</strong> in the top search bar</li>
            <li>Click <strong>"+ New registration"</strong></li>
            <li>Enter name: <strong>Founder Buddy</strong></li>
            <li>Select <strong>"Single tenant"</strong> for supported account types</li>
            <li>Click <strong>Register</strong></li>
            <li>On the overview page, copy:
                <ul style="list-style:disc;padding-left:20px;margin:8px 0">
                    <li><strong>Application (client) ID</strong> → Client ID</li>
                    <li><strong>Directory (tenant) ID</strong> → Tenant ID</li>
                </ul>
            </li>
            <li>Go to <strong>"Certificates & secrets"</strong> → <strong>"+ New client secret"</strong></li>
            <li>Copy the <strong>Value</strong> (not the Secret ID) → Client Secret</li>
            <li>Go to <strong>"API permissions"</strong> → <strong>"Add a permission"</strong></li>
        </ol>

        <h4>Required API Permissions</h4>
        <div class="permission-list">
            Microsoft Graph → Application permissions:<br>
            • ChannelMessage.Read.All<br>
            • Team.ReadBasic.All<br>
            • Channel.ReadBasic.All<br>
            • User.Read.All<br>
            • Mail.Read
        </div>

        <ol start="11">
            <li>After adding permissions, click <strong>"Grant admin consent"</strong></li>
        </ol>
    `;

    const GEMINI_HELP = `
        <h4>How to get your Gemini API Key</h4>
        <ol>
            <li>Go to <code>aistudio.google.com/apikey</code></li>
            <li>Sign in with your Google account</li>
            <li>Click <strong>"Create API Key"</strong></li>
            <li>Select or create a Google Cloud project</li>
            <li>Copy the generated API key</li>
        </ol>

        <h4>Important Notes</h4>
        <ol start="6">
            <li>The free tier includes 15 requests/minute — sufficient for Founder Buddy</li>
            <li>Keep your API key private — it is encrypted at rest in the database</li>
        </ol>
    `;

    // ─── Render Functions ──────────────────────────────────────

    function render(container) {
        container.innerHTML = '';
        container.style.display = 'block';

        const wrapper = document.createElement('div');
        wrapper.className = 'onboarding-container';

        const card = document.createElement('div');
        card.className = 'wizard-card';
        card.innerHTML = buildHeader() + buildStepDots() + '<div id="wizard-body"></div>';

        wrapper.appendChild(card);
        container.appendChild(wrapper);

        renderCurrentStep();
    }

    function buildHeader() {
        const titles = {
            1: { title: 'Connect Microsoft Azure', subtitle: 'Enter your Azure AD app registration credentials to access Teams & Outlook data.' },
            2: { title: 'Connect Gemini AI', subtitle: 'Enter your Gemini API key to power AI-driven analysis and insights.' },
            3: { title: 'Verify Connections', subtitle: 'Testing your credentials against Microsoft and Google services.' },
        };

        const step = titles[currentStep];
        const helpContent = currentStep === 1 ? 'azure' : currentStep === 2 ? 'gemini' : null;

        return `
            <div class="wizard-header">
                ${helpContent ? `<button class="wizard-help-btn" onclick="OnboardingWizard.showHelp('${helpContent}')" title="Setup guide">?</button>` : ''}
                <div class="wizard-logo">
                    <img src="/static/assets/logo.png" alt="Founder Buddy Logo" width="38" height="38" style="object-fit: contain; border-radius: 8px;">
                    <span class="wizard-logo-text">Founder Buddy</span>
                </div>
                <h2 class="wizard-title">${step.title}</h2>
                <p class="wizard-subtitle">${step.subtitle}</p>
            </div>
        `;
    }

    function buildStepDots() {
        let html = '<div class="wizard-steps">';
        for (let i = 1; i <= TOTAL_STEPS; i++) {
            const state = i < currentStep ? 'completed' : i === currentStep ? 'active' : '';
            html += `<div class="step-dot ${state}"></div>`;
            if (i < TOTAL_STEPS) {
                html += `<div class="step-connector ${i < currentStep ? 'completed' : ''}"></div>`;
            }
        }
        html += '</div>';
        return html;
    }

    function renderCurrentStep() {
        const body = document.getElementById('wizard-body');
        if (!body) return;

        // Re-render header + dots
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

    // ─── Step 1: Azure Credentials ─────────────────────────────

    function renderStep1(container) {
        container.innerHTML = `
            <form id="azure-form" class="wizard-form" onsubmit="OnboardingWizard.submitAzure(event)">
                <div class="form-group">
                    <label class="form-label">
                        Azure Tenant ID <span class="required">*</span>
                    </label>
                    <div class="input-wrapper">
                        <input
                            type="password"
                            id="azure-tenant-id"
                            class="form-input"
                            placeholder="e.g., 12345678-abcd-1234-abcd-123456789abc"
                            required
                            autocomplete="off"
                            spellcheck="false"
                        >
                        <span class="input-toggle" onclick="OnboardingWizard.togglePassword('azure-tenant-id', this)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        </span>
                    </div>
                    <span class="form-hint">Found in Azure AD → App registrations → Overview</span>
                </div>

                <div class="form-group">
                    <label class="form-label">
                        Client ID <span class="required">*</span>
                    </label>
                    <div class="input-wrapper">
                        <input
                            type="password"
                            id="azure-client-id"
                            class="form-input"
                            placeholder="e.g., 87654321-dcba-4321-dcba-987654321abc"
                            required
                            autocomplete="off"
                            spellcheck="false"
                        >
                        <span class="input-toggle" onclick="OnboardingWizard.togglePassword('azure-client-id', this)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        </span>
                    </div>
                    <span class="form-hint">Application (client) ID from your app registration</span>
                </div>

                <div class="form-group">
                    <label class="form-label">
                        Client Secret <span class="required">*</span>
                    </label>
                    <div class="input-wrapper">
                        <input
                            type="password"
                            id="azure-client-secret"
                            class="form-input"
                            placeholder="Enter your client secret value"
                            required
                            autocomplete="off"
                        >
                        <span class="input-toggle" onclick="OnboardingWizard.togglePassword('azure-client-secret', this)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        </span>
                    </div>
                    <span class="form-hint">The Value (not the Secret ID) from Certificates & secrets</span>
                </div>

                <div class="wizard-actions">
                    <div></div>
                    <button type="submit" id="azure-submit-btn" class="btn btn-primary btn-lg">
                        <span class="btn-text">Continue</span> →
                    </button>
                </div>
            </form>
        `;
    }

    // ─── Step 2: Gemini API Key ────────────────────────────────

    function renderStep2(container) {
        container.innerHTML = `
            <form id="gemini-form" class="wizard-form" onsubmit="OnboardingWizard.submitGemini(event)">
                <div class="form-group">
                    <label class="form-label">
                        Gemini API Key <span class="required">*</span>
                    </label>
                    <div class="input-wrapper">
                        <input
                            type="password"
                            id="gemini-api-key"
                            class="form-input"
                            placeholder="Enter your Gemini API key"
                            required
                            autocomplete="off"
                        >
                        <span class="input-toggle" onclick="OnboardingWizard.togglePassword('gemini-api-key', this)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        </span>
                    </div>
                    <span class="form-hint">Get it from aistudio.google.com/apikey</span>
                </div>

                <div class="wizard-actions">
                    <button type="button" class="btn btn-secondary" onclick="OnboardingWizard.goBack()">
                        ← Back
                    </button>
                    <button type="submit" id="gemini-submit-btn" class="btn btn-primary btn-lg">
                        <span class="btn-text">Continue</span> →
                    </button>
                </div>
            </form>
        `;
    }

    // ─── Step 3: Connection Test ───────────────────────────────

    function renderStep3(container) {
        container.innerHTML = `
            <div class="test-results" id="test-results">
                <div class="test-result-card pending" id="test-azure-card">
                    <div class="test-icon azure" style="font-weight: 800; font-size: 11px; color: var(--primary);">MS</div>
                    <div class="test-details">
                        <div class="test-name">Microsoft Azure</div>
                        <div class="test-message" id="test-azure-msg">Waiting to test...</div>
                    </div>
                    <div class="test-spinner" id="test-azure-spinner" style="display:none"></div>
                    <div class="test-status-icon" id="test-azure-status"></div>
                </div>

                <div class="test-result-card pending" id="test-gemini-card">
                    <div class="test-icon gemini" style="font-weight: 800; font-size: 11px; color: var(--secondary);">AI</div>
                    <div class="test-details">
                        <div class="test-name">Gemini AI</div>
                        <div class="test-message" id="test-gemini-msg">Waiting to test...</div>
                    </div>
                    <div class="test-spinner" id="test-gemini-spinner" style="display:none"></div>
                    <div class="test-status-icon" id="test-gemini-status"></div>
                </div>
            </div>

            <div class="wizard-actions">
                <button type="button" class="btn btn-secondary" onclick="OnboardingWizard.goBack()">
                    Back
                </button>
                <button type="button" id="test-btn" class="btn btn-primary btn-lg" onclick="OnboardingWizard.runTests()">
                    Test Connections
                </button>
            </div>

            <div id="test-complete-actions" style="display:none; margin-top: var(--space-4);">
                <div class="wizard-actions">
                    <button type="button" class="btn btn-secondary" onclick="OnboardingWizard.runTests()">
                        Re-test
                    </button>
                    <button type="button" id="finish-btn" class="btn btn-primary btn-lg" onclick="OnboardingWizard.finishOnboarding()">
                        <span class="btn-text">Get Started</span>
                    </button>
                </div>
            </div>
        `;
    }

    // ─── Action Handlers ───────────────────────────────────────

    async function submitAzure(e) {
        e.preventDefault();
        const btn = document.getElementById('azure-submit-btn');
        btn.classList.add('btn-loading');
        btn.disabled = true;

        const tenantId = document.getElementById('azure-tenant-id').value.trim();
        const clientId = document.getElementById('azure-client-id').value.trim();
        const clientSecret = document.getElementById('azure-client-secret').value.trim();

        try {
            await api.saveAzureCredentials(tenantId, clientId, clientSecret);
            showToast('Azure credentials saved', 'success');
            currentStep = 2;
            renderCurrentStep();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btn.classList.remove('btn-loading');
            btn.disabled = false;
        }
    }

    async function submitGemini(e) {
        e.preventDefault();
        const btn = document.getElementById('gemini-submit-btn');
        btn.classList.add('btn-loading');
        btn.disabled = true;

        const apiKey = document.getElementById('gemini-api-key').value.trim();

        try {
            await api.saveGeminiKey(apiKey);
            showToast('Gemini API key saved', 'success');
            currentStep = 3;
            renderCurrentStep();
        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            btn.classList.remove('btn-loading');
            btn.disabled = false;
        }
    }

    async function runTests() {
        const testBtn = document.getElementById('test-btn');
        const completeActions = document.getElementById('test-complete-actions');

        if (testBtn) {
            testBtn.classList.add('btn-loading');
            testBtn.disabled = true;
        }
        if (completeActions) completeActions.style.display = 'none';

        // Reset UI
        setTestState('azure', 'pending', 'Testing...');
        setTestState('gemini', 'pending', 'Testing...');

        // Show spinners
        showElement('test-azure-spinner');
        showElement('test-gemini-spinner');
        hideElement('test-azure-status');
        hideElement('test-gemini-status');

        try {
            const result = await api.testConnections(true, true);

            // Azure result
            const azure = result.results.azure;
            if (azure.tested) {
                setTestState('azure',
                    azure.success ? 'success' : 'error',
                    azure.message
                );
                hideElement('test-azure-spinner');
                const checkIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-success)" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>`;
                const crossIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-critical)" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
                const statusEl1 = document.getElementById('test-azure-status');
                if (statusEl1) statusEl1.innerHTML = azure.success ? checkIcon : crossIcon;
                showElement('test-azure-status');
            }

            // Gemini result
            const gemini = result.results.gemini;
            if (gemini.tested) {
                setTestState('gemini',
                    gemini.success ? 'success' : 'error',
                    gemini.message
                );
                hideElement('test-gemini-spinner');
                const checkIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-success)" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>`;
                const crossIcon = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--status-critical)" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
                const statusEl2 = document.getElementById('test-gemini-status');
                if (statusEl2) statusEl2.innerHTML = gemini.success ? checkIcon : crossIcon;
                showElement('test-gemini-status');
            }

            // Show finish button if all passed
            if (result.all_passed && completeActions) {
                completeActions.style.display = 'block';
                if (testBtn) testBtn.style.display = 'none';
                showToast('All connections verified!', 'success');
            } else {
                showToast('Some connections failed. Check the details and try again.', 'warning');
            }
        } catch (err) {
            showToast('Connection test failed: ' + err.message, 'error');
            setTestState('azure', 'error', 'Test failed');
            setTestState('gemini', 'error', 'Test failed');
            hideElement('test-azure-spinner');
            hideElement('test-gemini-spinner');
        } finally {
            if (testBtn) {
                testBtn.classList.remove('btn-loading');
                testBtn.disabled = false;
            }
        }
    }

    async function finishOnboarding() {
        const btn = document.getElementById('finish-btn');
        btn.classList.add('btn-loading');
        btn.disabled = true;

        try {
            await api.completeOnboarding();
            showToast('Welcome to Founder Buddy!', 'success');

            // Short delay for the toast to show, then transition
            setTimeout(() => {
                App.showIngestion();
            }, 800);
        } catch (err) {
            showToast(err.message, 'error');
            btn.classList.remove('btn-loading');
            btn.disabled = false;
        }
    }

    // ─── Navigation ────────────────────────────────────────────

    function goBack() {
        if (currentStep > 1) {
            currentStep--;
            renderCurrentStep();
        }
    }

    // ─── Help Modal ────────────────────────────────────────────

    function showHelp(type) {
        const modal = document.getElementById('help-modal');
        const title = document.getElementById('help-modal-title');
        const body = document.getElementById('help-modal-body');

        if (type === 'azure') {
            title.textContent = 'Azure Setup Guide';
            body.innerHTML = AZURE_HELP;
        } else if (type === 'gemini') {
            title.textContent = 'Gemini API Key Guide';
            body.innerHTML = GEMINI_HELP;
        }

        modal.style.display = 'flex';

        // Close handlers
        document.getElementById('help-modal-close').onclick = () => modal.style.display = 'none';
        modal.onclick = (e) => { if (e.target === modal) modal.style.display = 'none'; };
    }

    // ─── Password Toggle ──────────────────────────────────────

    function togglePassword(inputId, toggleEl) {
        const input = document.getElementById(inputId);
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

    // ─── UI Helpers ────────────────────────────────────────────

    function setTestState(service, state, message) {
        const card = document.getElementById(`test-${service}-card`);
        const msg = document.getElementById(`test-${service}-msg`);
        if (card) {
            card.className = `test-result-card ${state}`;
        }
        if (msg) msg.textContent = message;
    }

    function showElement(id) {
        const el = document.getElementById(id);
        if (el) el.style.display = '';
    }

    function hideElement(id) {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function cancelToDashboard() {
        App.showMainView();
    }

    // ─── Public API ────────────────────────────────────────────

    return {
        render,
        submitAzure,
        submitGemini,
        runTests,
        finishOnboarding,
        goBack,
        cancelToDashboard,
        showHelp,
        togglePassword,
    };
})();
