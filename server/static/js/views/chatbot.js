/**
 * Chatbot View Controller — assistant-ui ChatGPT-style Conversational UI.
 * Multi-session thread management (+ New Chat, Delete), Memory Context,
 * Suggestion Chips, Formatted Markdown, Copy-to-Clipboard, and Citation Expanders.
 */

const ChatbotView = (() => {
    let threads = [];
    let currentThreadId = null;
    let messages = [];

    // ─── Entry Point ──────────────────────────────────────────
    async function render(container) {
        container.innerHTML = `
            <div class="assistant-workspace">
                <!-- Left Sidebar: Multi-Session Chat Threads -->
                <div class="assistant-sidebar">
                    <div class="assistant-sidebar-header">
                        <button class="btn-new-chat" onclick="ChatbotView.createNewThread()">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                            New Chat
                        </button>
                    </div>
                    <div class="assistant-sidebar-list" id="assistant-threads-list">
                        <div style="padding: 16px; text-align: center; color: var(--text-tertiary); font-size: var(--text-xs);">Loading conversations...</div>
                    </div>
                </div>

                <!-- Main Chat Workspace -->
                <div class="assistant-main">
                    <!-- Header Bar -->
                    <div class="assistant-header">
                        <div class="assistant-header-title">
                            <span class="font-display font-semibold" style="font-size: var(--text-lg); color: var(--foreground);" id="active-thread-title">Ask Buddy</span>
                            <div class="assistant-status-pill" id="assistant-status-pill">
                                <span id="assistant-status-text">Buddy Active</span>
                            </div>
                        </div>
                    </div>

                    <!-- Messages Log Area -->
                    <div class="assistant-messages" id="assistant-messages-container">
                        <!-- Welcome / Empty State will be rendered here if no messages -->
                    </div>

                    <!-- Floating Input Bar -->
                    <div class="assistant-input-container">
                        <form id="assistant-input-form" onsubmit="ChatbotView.sendMessage(event)">
                            <div class="assistant-input-box">
                                <textarea
                                    id="assistant-textbox"
                                    class="assistant-textarea"
                                    placeholder="Ask Buddy a question about your team, projects, or emails..."
                                    rows="1"
                                    onkeydown="ChatbotView.handleKeyDown(event)"
                                ></textarea>
                                <button type="submit" class="btn-send-chat" id="assistant-send-btn" title="Send message">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>

            <!-- Citation Details Modal Overlay -->
            <div class="modal-overlay hidden" id="citation-modal" style="display: none;">
                <div class="modal-card" style="max-width: 680px; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-xl); padding: var(--space-6);">
                    <div class="modal-header" style="border-bottom: 1px solid var(--border); padding-bottom: var(--space-4); margin-bottom: var(--space-4); display:flex; justify-content:space-between;">
                        <h3 class="modal-title font-display" style="font-size: var(--text-xl); color: var(--foreground);" id="citation-modal-title">Source Conversation</h3>
                        <button class="modal-close" onclick="ChatbotView.closeCitation()">&times;</button>
                    </div>
                    <div class="modal-body" style="max-height: 480px; overflow-y: auto;">
                        <div style="font-size: var(--text-xs); color: var(--text-muted); display: flex; flex-direction: column; gap: 4px; border-bottom: 1px solid var(--border-subtle); padding-bottom: var(--space-3); margin-bottom: var(--space-4);">
                            <div id="citation-modal-meta-source">Source: </div>
                            <div id="citation-modal-meta-date">Date: </div>
                            <div id="citation-modal-meta-parts">Participants: </div>
                        </div>
                        <pre id="citation-modal-text" style="white-space: pre-wrap; font-size: var(--text-sm); line-height: 1.6; font-family: var(--font-sans); color: var(--foreground);"></pre>
                    </div>
                </div>
            </div>
        `;

        // Load chat threads and vector status
        await checkStatus();
        await loadThreads();
    }

    // ─── Status Check ──────────────────────────────────────────
    async function checkStatus() {
        try {
            const status = await api.request('GET', '/api/rag/status');
            const txt = document.getElementById('assistant-status-text');
            if (status.success && txt) {
                txt.textContent = `Buddy Active`;
            }
        } catch (e) {
            console.error('Failed to get RAG status:', e);
        }
    }

    // ─── Thread Management (Multi-Session Sidebar) ─────────────
    async function loadThreads() {
        const list = document.getElementById('assistant-threads-list');
        try {
            const res = await api.request('GET', '/api/rag/threads');
            if (res.success && res.threads) {
                threads = res.threads;
                renderThreadsList();

                if (threads.length > 0 && !currentThreadId) {
                    selectThread(threads[0].thread_id);
                } else if (threads.length === 0) {
                    renderEmptyWorkspace();
                }
            }
        } catch (err) {
            console.error('Failed to load chat threads:', err);
            if (list) list.innerHTML = `<div style="padding:16px; color:var(--status-critical); font-size:var(--text-xs);">Failed to load chat threads</div>`;
        }
    }

    function renderThreadsList() {
        const list = document.getElementById('assistant-threads-list');
        if (!list) return;

        if (threads.length === 0) {
            list.innerHTML = `<div style="padding:16px; text-align:center; color:var(--text-tertiary); font-size:var(--text-xs);">No past conversations</div>`;
            return;
        }

        list.innerHTML = threads.map(t => {
            const active = t.thread_id === currentThreadId ? 'active' : '';
            return `
                <div class="assistant-thread-item ${active}" onclick="ChatbotView.selectThread('${t.thread_id}')">
                    <span class="assistant-thread-title">${escapeHtml(t.title)}</span>
                    <button class="assistant-thread-del" onclick="ChatbotView.deleteThread(event, '${t.thread_id}')" title="Delete conversation">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                </div>
            `;
        }).join('');
    }

    async function createNewThread() {
        try {
            const res = await api.request('POST', '/api/rag/threads', { title: 'New Chat' });
            if (res.success && res.thread) {
                threads.unshift(res.thread);
                currentThreadId = res.thread.thread_id;
                renderThreadsList();
                renderEmptyWorkspace();
            }
        } catch (err) {
            showToast('Failed to create new chat: ' + err.message, 'error');
        }
    }

    async function deleteThread(e, threadId) {
        if (e) e.stopPropagation();
        if (!confirm('Delete this conversation session?')) return;

        try {
            await api.request('DELETE', `/api/rag/threads/${threadId}`);
            threads = threads.filter(t => t.thread_id !== threadId);

            if (currentThreadId === threadId) {
                currentThreadId = threads.length > 0 ? threads[0].thread_id : null;
            }

            renderThreadsList();
            if (currentThreadId) {
                selectThread(currentThreadId);
            } else {
                renderEmptyWorkspace();
            }
            showToast('Chat deleted', 'info');
        } catch (err) {
            showToast('Failed to delete chat: ' + err.message, 'error');
        }
    }

    async function selectThread(threadId) {
        currentThreadId = threadId;
        renderThreadsList();

        const activeT = threads.find(t => t.thread_id === threadId);
        const titleEl = document.getElementById('active-thread-title');
        if (titleEl && activeT) titleEl.textContent = activeT.title;

        const container = document.getElementById('assistant-messages-container');
        if (container) container.innerHTML = `<div style="padding:24px; text-align:center; color:var(--text-muted);">Loading conversation...</div>`;

        try {
            const res = await api.request('GET', `/api/rag/threads/${threadId}/messages`);
            if (res.success && res.messages) {
                messages = res.messages;
                if (messages.length === 0) {
                    renderEmptyWorkspace();
                } else {
                    renderMessagesLog();
                }
            }
        } catch (err) {
            console.error('Failed to load thread messages:', err);
        }
    }

    // ─── Render Messages Workspace ─────────────────────────────
    function renderEmptyWorkspace() {
        const container = document.getElementById('assistant-messages-container');
        if (!container) return;

        container.innerHTML = `
            <div class="assistant-welcome">
                <div class="assistant-welcome-icon">
                    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                </div>
                <h2 class="assistant-welcome-title">How can I help you today?</h2>
                <p class="assistant-welcome-desc">
                    Ask Buddy anything about your Microsoft Teams discussions, Outlook emails, project blockers, or key client deliverables.
                </p>
                <div class="suggestion-grid">
                    <div class="suggestion-card" onclick="ChatbotView.useSuggestion('What are the critical risks and blockers flagged this week?')">
                        <div class="suggestion-card-title">Weekly Blockers & Risks</div>
                        <div class="suggestion-card-sub">Extract unresolved issues from Teams & Outlook</div>
                    </div>
                    <div class="suggestion-card" onclick="ChatbotView.useSuggestion('Summarize recent client emails and external affairs updates.')">
                        <div class="suggestion-card-title">Client Email Summary</div>
                        <div class="suggestion-card-sub">Synthesize external communications and requests</div>
                    </div>
                    <div class="suggestion-card" onclick="ChatbotView.useSuggestion('What key decisions were made in project discussions?')">
                        <div class="suggestion-card-title">Key Project Decisions</div>
                        <div class="suggestion-card-sub">Find finalized roadmap agreements & approvals</div>
                    </div>
                    <div class="suggestion-card" onclick="ChatbotView.useSuggestion('List actionables assigned to team members.')">
                        <div class="suggestion-card-title">Actionables & Deliverables</div>
                        <div class="suggestion-card-sub">List tasks and pending follow-ups</div>
                    </div>
                </div>
            </div>
        `;
    }

    function renderMessagesLog() {
        const container = document.getElementById('assistant-messages-container');
        if (!container) return;

        container.innerHTML = '';
        messages.forEach(msg => {
            appendMessageBubble(msg.sender, msg.text, msg.sources, false);
        });

        container.scrollTop = container.scrollHeight;
    }

    function appendMessageBubble(sender, text, sources = null, scroll = true) {
        const container = document.getElementById('assistant-messages-container');
        if (!container) return;

        // Remove welcome if present
        const welcome = container.querySelector('.assistant-welcome');
        if (welcome) welcome.remove();

        const isUser = sender === 'user';
        const row = document.createElement('div');
        row.className = `chat-msg-row ${isUser ? 'chat-msg-user' : 'chat-msg-bot'}`;

        const avatarText = isUser ? 'YOU' : 'AI';
        const formattedText = isUser ? escapeHtml(text) : formatMarkdown(text);

        let citationsHtml = '';
        if (!isUser && sources && sources.length > 0) {
            citationsHtml = `
                <div class="chat-citations-container">
                    <div style="font-size: var(--text-xs); font-weight:700; color: var(--muted-foreground); margin-bottom: 2px;">Sources (${sources.length})</div>
                    <div style="display:flex; flex-wrap:wrap; gap:6px;">
                        ${sources.map((s, idx) => `
                            <span class="citation-pill" onclick="ChatbotView.showCitation(${idx}, ${JSON.stringify(s).replace(/"/g, '&quot;')})">
                                ${s.source === 'teams' ? 'Teams' : 'Outlook'}: ${escapeHtml(s.subject || 'Thread')}
                            </span>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        const actionsHtml = !isUser ? `
            <div class="chat-msg-actions">
                <span class="btn-copy-msg" onclick="ChatbotView.copyMessageText(this, ${JSON.stringify(text).replace(/"/g, '&quot;')})">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    Copy
                </span>
            </div>
        ` : '';

        row.innerHTML = `
            <div class="chat-msg-avatar">${avatarText}</div>
            <div class="chat-msg-card">
                <div>${formattedText}</div>
                ${citationsHtml}
                ${actionsHtml}
            </div>
        `;

        container.appendChild(row);
        if (scroll) container.scrollTop = container.scrollHeight;
    }

    // ─── Interaction Handlers ──────────────────────────────────
    function handleKeyDown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage(e);
        }
    }

    function useSuggestion(promptText) {
        const textbox = document.getElementById('assistant-textbox');
        if (textbox) {
            textbox.value = promptText;
            sendMessage();
        }
    }

    async function sendMessage(e) {
        if (e) e.preventDefault();

        const textbox = document.getElementById('assistant-textbox');
        const query = textbox.value.trim();
        if (!query) return;

        textbox.value = '';

        // If no active thread, create one first
        if (!currentThreadId) {
            try {
                const res = await api.request('POST', '/api/rag/threads', { title: query.slice(0, 36) });
                if (res.success && res.thread) {
                    threads.unshift(res.thread);
                    currentThreadId = res.thread.thread_id;
                    renderThreadsList();
                }
            } catch (err) {
                console.error('Failed to auto-create thread:', err);
            }
        }

        // Render user message bubble immediately
        appendMessageBubble('user', query);

        // Render assistant typing indicator
        const container = document.getElementById('assistant-messages-container');
        const typingRow = document.createElement('div');
        typingRow.className = 'chat-msg-row chat-msg-bot';
        typingRow.id = 'assistant-typing';
        typingRow.innerHTML = `
            <div class="chat-msg-avatar">AI</div>
            <div class="chat-msg-card">
                <div class="assistant-typing-dots">
                    <span></span><span></span><span></span>
                </div>
            </div>
        `;
        container.appendChild(typingRow);
        container.scrollTop = container.scrollHeight;

        // Call backend query endpoint
        try {
            const res = await api.request('POST', '/api/rag/query', {
                question: query,
                thread_id: currentThreadId
            });

            // Remove typing indicator
            const typing = document.getElementById('assistant-typing');
            if (typing) typing.remove();

            if (res.success) {
                appendMessageBubble('bot', res.answer, res.sources);
                // Refresh thread list to update order/title
                loadThreads();
            } else {
                appendMessageBubble('bot', res.answer || 'An error occurred processing your request.');
            }
        } catch (err) {
            const typing = document.getElementById('assistant-typing');
            if (typing) typing.remove();
            appendMessageBubble('bot', 'Failed to retrieve response: ' + err.message);
        }
    }

    function showCitation(idx, source) {
        const modal = document.getElementById('citation-modal');
        if (!modal || !source) return;

        const isTeams = source.source === 'teams' || (source.team_name || source.channel_name);
        const platformText = isTeams 
            ? `Microsoft Teams ${source.team_name ? '(' + source.team_name + (source.channel_name ? ' > #' + source.channel_name : '') + ')' : ''}`
            : `Outlook Email`;

        document.getElementById('citation-modal-title').textContent = source.subject || 'Source Conversation';
        document.getElementById('citation-modal-meta-source').textContent = `Source Platform: ${platformText}`;
        document.getElementById('citation-modal-meta-date').textContent = `Date: ${source.date || 'Recent'}`;
        document.getElementById('citation-modal-meta-parts').textContent = `Participants: ${source.participants || 'Team Members'}`;
        
        const excerptText = source.text || source.raw_text;
        if (excerptText) {
            document.getElementById('citation-modal-text').textContent = excerptText;
        } else {
            document.getElementById('citation-modal-text').textContent = `[Retrieved Source Conversation Excerpt]\nThread ID: ${source.thread_id}\nRelevance Score: ${Math.round((source.relevance || 0.85) * 100)}%`;
        }

        modal.style.display = 'flex';
        modal.classList.remove('hidden');
    }

    function closeCitation() {
        const modal = document.getElementById('citation-modal');
        if (modal) {
            modal.style.display = 'none';
            modal.classList.add('hidden');
        }
    }

    function copyMessageText(btn, text) {
        navigator.clipboard.writeText(text);
        const orig = btn.innerHTML;
        btn.innerHTML = `Copied`;
        setTimeout(() => { btn.innerHTML = orig; }, 1800);
    }

    async function triggerIndexing() {
        showToast('Triggering vector store indexing...', 'info');
        try {
            const res = await api.request('POST', '/api/rag/index', { clear_first: false });
            showToast(res.message || 'Indexing started in background.', 'success');
            setTimeout(() => checkStatus(), 3000);
        } catch (err) {
            showToast('Indexing failed: ' + err.message, 'error');
        }
    }

    // ─── Helper Functions ──────────────────────────────────────
    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function formatMarkdown(text) {
        if (!text) return '';
        
        let cleanText = text;

        // 1. Strip raw JSON string or JSON codeblock wrapper if model returned JSON
        if (typeof cleanText === 'string') {
            cleanText = cleanText.trim();

            // Strip ```json ... ```
            if (cleanText.startsWith('```')) {
                const lines = cleanText.split('\n');
                if (lines[0].startsWith('```json') || lines[0].startsWith('```markdown') || lines[0].startsWith('```')) {
                    if (lines[lines.length - 1].startsWith('```')) {
                        cleanText = lines.slice(1, -1).join('\n').trim();
                    }
                }
            }

            // Parse JSON if cleanText is a JSON string containing answer/response
            if (cleanText.startsWith('{') && cleanText.endsWith('}')) {
                try {
                    const parsed = JSON.parse(cleanText);
                    if (parsed.answer) cleanText = parsed.answer;
                    else if (parsed.response) cleanText = parsed.response;
                    else if (parsed.content) cleanText = parsed.content;
                } catch (e) {}
            }
        }

        // 2. Extract and preserve Code Blocks (fenced ```code```)
        const codeBlocks = [];
        cleanText = cleanText.replace(/```(\w+)?\n([\s\S]*?)```/g, (match, lang, code) => {
            const placeholder = `___CODEBLOCK_${codeBlocks.length}___`;
            codeBlocks.push(`
                <pre style="background: #0F172A; color: #F8FAFC; padding: 14px 16px; border-radius: 10px; font-family: var(--font-mono); font-size: 13px; overflow-x: auto; margin: 12px 0; border: 1px solid #1E293B;">
                    <code>${escapeHtml(code.trim())}</code>
                </pre>
            `);
            return placeholder;
        });

        // 3. Escape HTML to prevent XSS on remaining text
        let html = escapeHtml(cleanText);

        // 4. Headings (# ## ###)
        html = html.replace(/^### (.*$)/gim, '<h3 style="font-size: 15px; font-weight: 800; color: #0F172A; margin: 16px 0 8px 0; border-bottom: 1px solid #E2E8F0; padding-bottom: 4px;">$1</h3>');
        html = html.replace(/^## (.*$)/gim, '<h2 style="font-size: 17px; font-weight: 800; color: #0F172A; margin: 18px 0 10px 0;">$1</h2>');
        html = html.replace(/^# (.*$)/gim, '<h1 style="font-size: 19px; font-weight: 800; color: #0F172A; margin: 20px 0 12px 0;">$1</h1>');

        // 5. Bold, Italic & Inline Code
        html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong style="color: #0F172A; font-weight: 700;">$1</strong>');
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
        html = html.replace(/`([^`]+)`/g, '<code style="background: rgba(0, 82, 255, 0.08); color: #0052FF; padding: 2px 6px; border-radius: 4px; font-family: var(--font-mono); font-size: 12px; font-weight: 600;">$1</code>');

        // 6. Blockquotes (> text)
        html = html.replace(/^&gt;\s+(.*$)/gim, '<blockquote style="border-left: 3px solid #0052FF; background: #F8FAFC; padding: 8px 12px; margin: 10px 0; color: #475569; font-style: italic; border-radius: 0 6px 6px 0;">$1</blockquote>');

        // 7. Process Lines for Lists & Paragraphs
        const lines = html.split('\n');
        let inList = false;
        let inNumList = false;
        let processedLines = [];

        lines.forEach(line => {
            const trimLine = line.trim();
            const bulletMatch = trimLine.match(/^(?:&bull;|\*|-)\s+(.*)/);
            const numMatch = trimLine.match(/^(\d+)\.\s+(.*)/);

            if (bulletMatch) {
                if (inNumList) { processedLines.push('</ol>'); inNumList = false; }
                if (!inList) { processedLines.push('<ul style="margin: 8px 0 12px 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px;">'); inList = true; }
                processedLines.push(`<li style="line-height: 1.5; color: #334155;">${bulletMatch[1]}</li>`);
            } else if (numMatch) {
                if (inList) { processedLines.push('</ul>'); inList = false; }
                if (!inNumList) { processedLines.push('<ol style="margin: 8px 0 12px 0; padding-left: 20px; display: flex; flex-direction: column; gap: 6px;">'); inNumList = true; }
                processedLines.push(`<li style="line-height: 1.5; color: #334155;">${numMatch[2]}</li>`);
            } else {
                if (inList) { processedLines.push('</ul>'); inList = false; }
                if (inNumList) { processedLines.push('</ol>'); inNumList = false; }

                if (trimLine.startsWith('<h') || trimLine.startsWith('<blockquote') || trimLine.startsWith('___CODEBLOCK_')) {
                    processedLines.push(trimLine);
                } else if (trimLine === '') {
                    processedLines.push('<div style="height: 6px;"></div>');
                } else {
                    processedLines.push(`<p style="margin: 0 0 8px 0; line-height: 1.6; color: #334155;">${trimLine}</p>`);
                }
            }
        });

        if (inList) processedLines.push('</ul>');
        if (inNumList) processedLines.push('</ol>');

        let finalHtml = processedLines.join('\n');

        // 8. Restore Fenced Code Blocks
        codeBlocks.forEach((block, idx) => {
            finalHtml = finalHtml.replace(`___CODEBLOCK_${idx}___`, block);
        });

        return finalHtml;
    }

    // ─── Public API ────────────────────────────────────────────
    return {
        render,
        createNewThread,
        deleteThread,
        selectThread,
        sendMessage,
        handleKeyDown,
        useSuggestion,
        showCitation,
        closeCitation,
        copyMessageText
    };
})();
