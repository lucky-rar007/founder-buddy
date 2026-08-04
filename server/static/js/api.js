/**
 * API Client — Centralized HTTP client for all backend calls.
 *
 * Provides typed methods for each API endpoint, handles errors,
 * and exports a singleton `api` object.
 */

const api = (() => {
    const BASE_URL = '';  // Same origin

    /**
     * Make an HTTP request to the backend.
     * @param {string} method - HTTP method (GET, POST, etc.)
     * @param {string} path - API path (e.g., /api/onboarding/status)
     * @param {object|null} body - Request body for POST/PUT
     * @returns {Promise<object>} Parsed JSON response
     */
    async function request(method, path, body = null) {
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };

        if (body && method !== 'GET') {
            options.body = JSON.stringify(body);
        }

        try {
            const response = await fetch(`${BASE_URL}${path}`, options);

            // Parse response
            let data;
            try {
                data = await response.json();
            } catch {
                data = { success: false, error: `HTTP ${response.status}: Non-JSON response` };
            }

            if (!response.ok) {
                const errorMsg = data.detail || data.error || `HTTP ${response.status}`;
                throw new Error(errorMsg);
            }

            return data;
        } catch (err) {
            if (err.name === 'TypeError' && err.message.includes('fetch')) {
                throw new Error('Could not connect to the server. Is it running?');
            }
            throw err;
        }
    }

    return {
        // Expose general request method for flexibility
        request,

        // ─── Onboarding ────────────────────────────────────
        getOnboardingStatus() {
            return request('GET', '/api/onboarding/status');
        },

        saveAzureCredentials(tenantId, clientId, clientSecret) {
            return request('POST', '/api/onboarding/azure-credentials', {
                tenant_id: tenantId,
                client_id: clientId,
                client_secret: clientSecret,
            });
        },

        saveGeminiKey(apiKey) {
            return request('POST', '/api/onboarding/gemini-key', {
                api_key: apiKey,
            });
        },

        testConnections(testAzure = true, testGemini = true) {
            return request('POST', '/api/onboarding/test-connection', {
                test_azure: testAzure,
                test_gemini: testGemini,
            });
        },

        completeOnboarding() {
            return request('POST', '/api/onboarding/complete');
        },

        // ─── Config ────────────────────────────────────────
        getAllConfig() {
            return request('GET', '/api/config/all');
        },

        getConfig(key) {
            return request('GET', `/api/config/get/${encodeURIComponent(key)}`);
        },

        setConfig(key, value, encrypt = false) {
            return request('POST', '/api/config/set', { key, value, encrypt });
        },

        getOnboardingConfigStatus() {
            return request('GET', '/api/config/onboarding-status');
        },

        // ─── Ingestion ─────────────────────────────────────
        getIngestionStatus() {
            return request('GET', '/api/ingestion/status');
        },

        // ─── Health ────────────────────────────────────────
        healthCheck() {
            return request('GET', '/health');
        },
    };
})();
