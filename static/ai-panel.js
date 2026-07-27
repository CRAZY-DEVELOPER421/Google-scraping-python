/**
 * AI Search Panel — Fresh Build
 * Simple, robust frontend with toggle, auto-trigger, chat, and results display.
 */
(function() {
    "use strict";

    let panelOpen = false;
    let currentSearch = { query: '', results: [], fields: ['name','address','email','phone_number','website'], abortCtrl: null, inProgress: false, searchId: null };
    let typeTimer = null;

    // ─── Inject HTML ────────────────────────────────────

    function injectHTML() {
        if (document.getElementById('ai-panel')) return;
        const div = document.getElementById('ai-panel-root');
        if (!div) return;
        div.innerHTML = `
        <div id="ai-panel-toggle-chip" title="Toggle AI Search"><span class="chip-icon">►</span></div>
        <div id="ai-panel">
          <div class="ai-panel-header">
            <div class="title"><span class="badge">AI</span> Search <span class="badge">Zaucto</span></div>
            <div style="display:flex;align-items:center;gap:8px">
              <span class="usage" id="aiUsage">0/2500</span>
              <span class="ai-status" id="aiStatus"></span>
              <button class="ai-close-btn" id="aiCloseBtn">✕</button>
            </div>
          </div>
          <div class="ai-content">
            <div class="ai-query" id="aiQuery" style="display:none">
              <div class="qb-label">Search Query</div>
              <div class="qb-text" id="aiQueryText"></div>
            </div>
            <div class="ai-count" id="aiCount" style="display:none"><span id="aiCountText">0 results</span></div>
            <div class="ai-loading" id="aiLoading" style="display:none">
              <div class="ai-spinner"></div>
              <div class="ai-loading-text">Searching with Zaucto AI...</div>
              <div class="ai-loading-sub" style="font-size:11px;color:#9ca3af;margin-top:4px;">This may take 30-60 seconds for best results</div>
            </div>
            <div class="ai-empty" id="aiEmpty">
              <div class="ai-empty-icon">🔍</div>
              <div>No results yet</div>
              <div class="ai-empty-sub">Enable AI Search and click Start Scraping</div>
            </div>
            <div class="ai-error" id="aiError" style="display:none">
              <div>⚠️</div>
              <div id="aiErrorText">Error</div>
            </div>
            <div class="ai-results" id="aiResults" style="display:none">
              <table class="ai-table"><thead id="aiThead"></thead><tbody id="aiTbody"></tbody></table>
              <!-- Action Buttons -->
              <div class="ai-actions" id="aiActions" style="display:none">
                <button class="ai-action-btn csv" id="aiBtnCsv" title="Download as CSV"><span class="aicon">📄</span> CSV</button>
                <button class="ai-action-btn json" id="aiBtnJson" title="Download as JSON"><span class="aicon">{ }</span> JSON</button>
                <button class="ai-action-btn copy" id="aiBtnCopy" title="Copy to clipboard"><span class="aicon">📋</span> Copy</button>
                <button class="ai-action-btn stop" id="aiBtnStop" title="Stop search"><span class="aicon">⏹</span> Stop</button>
                <button class="ai-action-btn clear" id="aiBtnClear" title="Clear results"><span class="aicon">🗑</span> Clear</button>
              </div>
            </div>
          </div>
          <div class="ai-toast" id="aiToast"></div>
          <div class="ai-chat">
            <div class="ai-chat-messages" id="aiChatMsgs"></div>
            <div class="ai-chat-input-wrap">
              <input class="ai-chat-input" id="aiChatInput" placeholder="Ask business questions..." />
              <button class="ai-chat-send" id="aiChatSend">►</button>
            </div>
          </div>
        </div>`;
        document.body.appendChild(div);
    }

    // ─── UI Helpers ─────────────────────────────────────

    function show(id) { const e = document.getElementById(id); if (e) e.style.display = ''; }
    function hide(id) { const e = document.getElementById(id); if (e) e.style.display = 'none'; }
    function status(state) {
        const s = document.getElementById('aiStatus');
        if (!s) return;
        s.className = 'ai-status' + (state ? ' ' + state : '');
    }

    function toast(msg, type) {
        const t = document.getElementById('aiToast');
        if (!t) return;
        t.textContent = msg; t.className = 'ai-toast';
        if (type) t.classList.add('ai-toast-' + type);
        t.classList.add('visible');
        setTimeout(() => t.classList.remove('visible'), 3000);
    }

    function render() {
        const { results, fields, query } = currentSearch;
        hide('aiLoading'); hide('aiError');

        const qb = document.getElementById('aiQuery');
        const qt = document.getElementById('aiQueryText');
        if (query) { qb.style.display = ''; qt.textContent = query; } else { qb.style.display = 'none'; }

        const cc = document.getElementById('aiCount');
        const ct = document.getElementById('aiCountText');
        if (results.length > 0) { cc.style.display = ''; ct.textContent = results.length + ' results'; } else { cc.style.display = 'none'; }

        if (currentSearch.inProgress) { show('aiLoading'); hide('aiActions'); status('searching'); return; }

        if (results.length === 0) {
            show('aiEmpty'); hide('aiActions'); status('');
            const sub = document.querySelector('.ai-empty-sub');
            if (sub) sub.textContent = query ? 'AI search found no results. Try a different keyword.' : 'Enable AI Search and click Start Scraping';
            return;
        }
        hide('aiEmpty'); show('aiResults'); show('aiActions'); status('done');

        const thead = document.getElementById('aiThead');
        const tbody = document.getElementById('aiTbody');
        let h = '<tr>', b = '';
        for (const f of fields) {
            const label = f.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
            h += '<th>' + label + '</th>';
        }
        h += '</tr>';
        for (const item of results) {
            b += '<tr>';
            for (const f of fields) {
                let v = item[f]; if (v === undefined || v === null) v = '';
                let d = v, cls = '';
                if (f === 'name') cls = 'ai-name';
                else if (f === 'website' && v) d = '<a href="' + v + '" target="_blank">' + (v.length > 30 ? v.slice(0,30)+'…' : v) + '</a>';
                else if (f === 'phone_number' && v) d = '<span>' + v + '</span>';
                if (!v) d = '<span class="ai-empty-field">—</span>';
                b += '<td class="' + cls + '">' + d + '</td>';
            }
            b += '</tr>';
        }
        thead.innerHTML = h; tbody.innerHTML = b;
    }

    // ─── Action Buttons ────────────────────────────────

    function resultsToCSV() {
        const { results, fields } = currentSearch;
        if (!results.length) return '';
        let csv = fields.map(f => f.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())).join(',') + '\n';
        for (const item of results) {
            const row = fields.map(f => {
                let v = item[f] || '';
                if (v.includes(',') || v.includes('"') || v.includes('\n')) v = '"' + v.replace(/"/g,'""') + '"';
                return v;
            });
            csv += row.join(',') + '\n';
        }
        return csv;
    }

    function downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function exportCSV() {
        if (!currentSearch.results.length) { toast('No results to export', 'error'); return; }
        const csv = resultsToCSV();
        const querySlug = (currentSearch.query || 'search').slice(0,20).replace(/[^a-zA-Z0-9]/g,'_');
        downloadFile(csv, `zaucto_ai_${querySlug}.csv`, 'text/csv;charset=utf-8;');
        toast('CSV downloaded!', 'success');
    }

    function exportJSON() {
        if (!currentSearch.results.length) { toast('No results to export', 'error'); return; }
        const json = JSON.stringify({ query: currentSearch.query, results: currentSearch.results }, null, 2);
        const querySlug = (currentSearch.query || 'search').slice(0,20).replace(/[^a-zA-Z0-9]/g,'_');
        downloadFile(json, `zaucto_ai_${querySlug}.json`, 'application/json;charset=utf-8;');
        toast('JSON downloaded!', 'success');
    }

    function copyResults() {
        if (!currentSearch.results.length) { toast('No results to copy', 'error'); return; }
        const csv = resultsToCSV();
        navigator.clipboard.writeText(csv).then(() => {
            toast('Copied to clipboard!', 'success');
        }).catch(() => {
            // Fallback for older browsers
            const ta = document.createElement('textarea');
            ta.value = csv; ta.style.position = 'fixed'; ta.style.opacity = '0';
            document.body.appendChild(ta); ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            toast('Copied to clipboard!', 'success');
        });
    }

    function stopSearch() {
        if (currentSearch.abortCtrl) {
            currentSearch.abortCtrl.abort();
            currentSearch.abortCtrl = null;
        }
        currentSearch.inProgress = false;
        hide('aiLoading');
        status('');
        toast('Search stopped', 'info');
    }

    function clearResults() {
        if (currentSearch.abortCtrl) {
            currentSearch.abortCtrl.abort();
            currentSearch.abortCtrl = null;
        }
        currentSearch = { query: '', results: [], fields: ['name','address','email','phone_number','website'],
            abortCtrl: null, inProgress: false, searchId: null };
        hide('aiLoading'); hide('aiResults'); hide('aiActions'); hide('aiError');
        show('aiEmpty'); status('');
        const sub = document.querySelector('.ai-empty-sub');
        if (sub) sub.textContent = 'Enable AI Search and click Start Scraping';
        // Clear chat messages
        const chatMsgs = document.getElementById('aiChatMsgs');
        if (chatMsgs) chatMsgs.innerHTML = '';
        // Clear query display
        const qt = document.getElementById('aiQueryText');
        if (qt) qt.textContent = '';
        document.getElementById('aiQuery').style.display = 'none';
        document.getElementById('aiCount').style.display = 'none';
        toast('Results cleared', 'info');
    }

    // ─── Panel Toggle ───────────────────────────────────

    function openPanel() {
        const p = document.getElementById('ai-panel');
        const c = document.getElementById('ai-panel-toggle-chip');
        if (p) p.classList.add('open');
        if (c) c.classList.add('open');
        panelOpen = true;
        fetchUsage();
    }
    function closePanel() {
        const p = document.getElementById('ai-panel');
        const c = document.getElementById('ai-panel-toggle-chip');
        if (p) p.classList.remove('open');
        if (c) c.classList.remove('open');
        panelOpen = false;
    }
    function togglePanel() { panelOpen ? closePanel() : openPanel(); }
    window.openAIPanel = openPanel;
    window.closeAIPanel = closePanel;

    // ─── Usage ──────────────────────────────────────────

    async function fetchUsage() {
        try {
            const r = await fetch('/api/ai-search/usage');
            const u = await r.json();
            const el = document.getElementById('aiUsage');
            if (el) el.textContent = u.used + '/' + u.limit + ' (' + u.remaining + ' left)';
        } catch(e) {}
    }

    // ─── Trigger AI Search ──────────────────────────────

    function buildQuery(filter, results, keyword, location) {
        return keyword + ' in ' + location;
    }

    async function triggerAI(keyword, location, results, filter, mode, jobId) {
        if (currentSearch.abortCtrl) currentSearch.abortCtrl.abort();
        const ac = new AbortController();
        const query = buildQuery(filter, results, keyword, location);
        currentSearch = { query, results: [], fields: ['name','address','email','phone_number','website'],
            abortCtrl: ac, inProgress: true, searchId: Date.now().toString(36) + Math.random().toString(36).slice(2,6) };
        render();
        try {
            const r = await fetch('/api/ai-search/start', {
                method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({ keyword, location, results: parseInt(results)||10, filter, mode }),
                signal: ac.signal,
            });
            let data;
            try { data = await r.json(); } catch(e) { throw new Error('Invalid server response ('+r.status+')'); }
            if (data.error) throw new Error(data.error);
            if (!r.ok) throw new Error('Server error ('+r.status+')');
            if (Array.isArray(data.results)) {
                currentSearch.results = data.results;
                currentSearch.searchId = data.search_id || currentSearch.searchId;
                currentSearch.fields = ['name','address','email','phone_number','website'];
                if (data.results.length === 0) {
                    toast('AI Search: no businesses found in web results (main scrape may still return data)', 'info');
                } else if (jobId) {
                    // Store AI results in the scrape job for email attachment
                    fetch('/scrape/job/' + jobId + '/ai-results', {
                        method: 'POST', headers: {'Content-Type':'application/json'},
                        body: JSON.stringify({ results: data.results }),
                    }).catch(function(err) {
                        console.warn('Could not store AI results in job:', err);
                    });
                }
                if (data.usage) {
                    const el = document.getElementById('aiUsage');
                    if (el) el.textContent = data.usage.used + '/' + data.usage.limit + ' (' + data.usage.remaining + ' left)';
                }
            } else throw new Error('Invalid response format');
        } catch(err) {
            if (err.name === 'AbortError') {
                currentSearch.results = []; currentSearch.fields = [];
                toast('Search cancelled', 'error');
            } else {
                currentSearch.results = []; currentSearch.fields = [];
                document.getElementById('aiErrorText').textContent = err.message || 'Failed';
                show('aiError'); status('error');
                toast('Search failed: '+err.message, 'error');
            }
        } finally {
            currentSearch.inProgress = false;
            if (currentSearch.abortCtrl === ac) render();
        }
    }
    window.triggerAISearch = triggerAI;

    // ─── Chat ────────────────────────────────────────────

    function sendMsg() {
        const input = document.getElementById('aiChatInput');
        if (!input) return;
        const q = input.value.trim();
        if (!q) return;
        input.value = '';

        if (currentSearch.abortCtrl) currentSearch.abortCtrl.abort();

        // Show user message
        appendChat('user', q);
        appendChat('ai', 'Searching...');
        hide('aiEmpty'); hide('aiResults'); show('aiLoading'); status('searching');

        const modeEl = document.querySelector('.mode-btn.active');
        const mode = modeEl ? modeEl.dataset.mode : 'fast';
        const totalEl = document.getElementById('total');
        const count = Math.max(3, parseInt(totalEl ? totalEl.value : 10) || 10);

        fetch('/api/ai-search/chat', {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ query: q, mode, results: count }),
        }).then(r => r.json()).then(data => {
            removeLastChat();
            if (data.type === 'search_result' && Array.isArray(data.results)) {
                appendChat('ai', data.message || 'Here are the results:');
                if (data.results.length > 0) {
                    currentSearch.results = data.results;
                    currentSearch.query = q;
                    currentSearch.searchId = data.search_id || Date.now().toString(36);
                    currentSearch.fields = ['name','address','email','phone_number','website'];
                    if (data.usage) {
                        const el = document.getElementById('aiUsage');
                        if (el) el.textContent = data.usage.used+'/'+data.usage.limit+' ('+data.usage.remaining+' left)';
                    }
                    hide('aiLoading'); status('done');
                    render();
                } else {
                    hide('aiLoading'); show('aiEmpty'); status('');
                    toast('No results for your query', 'error');
                }
            } else if (data.type === 'refusal') {
                removeLastChat();
                appendChat('ai', data.message || 'I can only help with business data.');
                hide('aiLoading'); show('aiEmpty'); status('');
            } else if (data.error) {
                removeLastChat();
                appendChat('ai', 'Error: '+data.error);
                hide('aiLoading'); show('aiEmpty'); status('error');
            }
        }).catch(err => {
            removeLastChat();
            appendChat('ai', 'Failed: '+err.message);
            hide('aiLoading'); show('aiEmpty'); status('error');
            toast('Chat failed', 'error');
        });
    }

    // ─── Chat Helpers ────────────────────────────────────

    function appendChat(sender, text) {
        const c = document.getElementById('aiChatMsgs');
        if (!c) return;
        if (typeTimer) { clearTimeout(typeTimer); typeTimer = null; }
        const safe = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        const d = document.createElement('div');
        d.className = 'ai-chat-msg ' + sender;
        if (sender === 'user') {
            d.textContent = 'You: ' + safe;
            c.appendChild(d); c.scrollTop = c.scrollHeight; return;
        }
        d.textContent = 'AI: '; c.appendChild(d); d.classList.add('typing');
        let i = 0;
        function type() {
            if (i < safe.length) { d.textContent += safe[i]; i++; c.scrollTop = c.scrollHeight; typeTimer = setTimeout(type, 20); }
            else { d.classList.remove('typing'); typeTimer = null; c.scrollTop = c.scrollHeight; }
        }
        type();
    }
    function removeLastChat() {
        const c = document.getElementById('aiChatMsgs');
        if (!c) return;
        const last = c.lastElementChild;
        if (last) last.remove();
    }

    // ─── Wire Events ────────────────────────────────────

    function wire() {
        document.getElementById('ai-panel-toggle-chip').addEventListener('click', togglePanel);
        document.getElementById('aiCloseBtn').addEventListener('click', function(e) { e.stopPropagation(); closePanel(); });
        document.getElementById('aiChatSend').addEventListener('click', sendMsg);
        document.getElementById('aiChatInput').addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
        });
        const aiToggle = document.getElementById('aiSearchToggle');
        if (aiToggle) {
            aiToggle.addEventListener('change', function() {
                if (this.checked) { openPanel(); toast('AI Search is ON', 'success'); }
            });
        }
        
        // Action buttons
        document.getElementById('aiBtnCsv').addEventListener('click', exportCSV);
        document.getElementById('aiBtnJson').addEventListener('click', exportJSON);
        document.getElementById('aiBtnCopy').addEventListener('click', copyResults);
        document.getElementById('aiBtnStop').addEventListener('click', stopSearch);
        document.getElementById('aiBtnClear').addEventListener('click', clearResults);
    }

    // ─── Init ────────────────────────────────────────────

    function init() {
        injectHTML();
        wire();
        setTimeout(() => { hide('aiLoading'); show('aiEmpty'); status(''); fetchUsage(); }, 100);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
