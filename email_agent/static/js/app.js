/**
 * 服装智能助手 - 前端主逻辑
 */

const API_BASE = '';
let token = localStorage.getItem('agent_token');
let currentUser = null;
let currentSessionId = null;

// ========== 页面初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
    if (token) {
        verifyToken();
    } else {
        showLoginPage();
    }
    
    bindEvents();
});

function bindEvents() {
    // 登录
    document.getElementById('login-btn').addEventListener('click', doLogin);
    document.getElementById('email-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') doLogin();
    });
    
    // 退出
    document.getElementById('logout-btn').addEventListener('click', doLogout);
    
    // 发送消息
    const sendBtn = document.getElementById('send-btn');
    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }
    document.getElementById('chat-input').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
}

// ========== 认证 ==========
async function doLogin() {
    const email = document.getElementById('email-input').value.trim();
    if (!email) {
        showError('请输入邮箱号');
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        
        const data = await res.json();
        if (!res.ok) {
            showError(data.detail || '登录失败');
            return;
        }
        
        token = data.token;
        currentUser = data;
        localStorage.setItem('agent_token', token);
        
        showMainPage();
    } catch (err) {
        showError('网络错误，请稍后重试');
    }
}

async function verifyToken() {
    try {
        const res = await fetch(`${API_BASE}/api/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (res.ok) {
            currentUser = await res.json();
            showMainPage();
        } else {
            localStorage.removeItem('agent_token');
            token = null;
            showLoginPage();
        }
    } catch (err) {
        showLoginPage();
    }
}

async function doLogout() {
    if (token) {
        await fetch(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
    }
    
    localStorage.removeItem('agent_token');
    token = null;
    currentUser = null;
    currentSessionId = null;
    showLoginPage();
}

function showError(msg) {
    document.getElementById('login-error').textContent = msg;
}

// ========== 页面切换 ==========
function showLoginPage() {
    document.getElementById('login-page').classList.remove('hidden');
    document.getElementById('main-page').classList.add('hidden');
}

function showMainPage() {
    document.getElementById('login-page').classList.add('hidden');
    document.getElementById('main-page').classList.remove('hidden');
    
    document.getElementById('user-name').textContent = currentUser?.name || currentUser?.email;
    
    // 加载数据
    loadMorningPush();
    loadMyStyles();
    loadHistory();
}

// ========== 侧边栏 ==========
function toggleSection(id) {
    const el = document.getElementById(id);
    const header = document.getElementById('header-' + id);
    el.classList.toggle('collapsed');
    if (header) {
        header.classList.toggle('collapsed');
    }
}

// ========== 新对话 ==========
function startNewChat() {
    currentSessionId = null;
    document.getElementById('chat-messages').innerHTML = '';
}

// ========== 今日汇总 ==========
async function loadMorningPush() {
    try {
        const res = await fetch(`${API_BASE}/api/morning-push`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!res.ok) throw new Error('加载失败');
        
        const data = await res.json();
        document.getElementById('morning-push-content').innerHTML = marked(data.content);
    } catch (err) {
        document.getElementById('morning-push-content').innerHTML = '<p class="error">加载失败，请刷新重试</p>';
    }
}

// ========== 我负责的 ==========
async function loadMyStyles() {
    try {
        const res = await fetch(`${API_BASE}/api/styles`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!res.ok) throw new Error('加载失败');
        
        const styles = await res.json();
        const container = document.getElementById('styles-list');
        
        if (styles.length === 0) {
            container.innerHTML = '<p style="color:#999;font-size:13px;">暂无款号数据</p>';
            return;
        }
        const list = styles.slice(1,5)
        container.innerHTML = list.map(s => `
                <div class="style-item ${s.is_pinned ? 'pinned' : ''}" onclick="quickAsk('${s.style_id}')">
                <span>${s.style_id}</span>
                ${s.alias ? `<span class="style-alias">${s.alias}</span>` : ''}
                </div>`).join('');
    } catch (err) {
        document.getElementById('styles-list').innerHTML = '<p class="error">加载失败</p>';
    }
}

function quickAsk(styleId) {
    document.getElementById('chat-input').value = `${styleId} 进度`;
    sendMessage();
}

// ========== 历史会话 ==========
async function loadHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/sessions`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!res.ok) throw new Error('加载失败');
        
        const sessions = await res.json();
        const container = document.getElementById('history-list');
        
        if (sessions.length === 0) {
            container.innerHTML = '<p style="color:#999;font-size:13px;">暂无历史会话</p>';
            return;
        }
        
        // 按日期分组
        const groups = groupSessionsByDate(sessions);
        
        container.innerHTML = Object.entries(groups).map(([date, items]) => `
            <div class="history-group">
                <div class="history-group-title">${date}</div>
                ${items.map(s => `
                    <div class="history-item" onclick="loadSession(${s.id})">
                        ${s.title || '新会话'}
                    </div>
                `).join('')}
            </div>
        `).join('');
    } catch (err) {
        document.getElementById('history-list').innerHTML = '<p class="error">加载失败</p>';
    }
}

function groupSessionsByDate(sessions) {
    const groups = {};
    const today = new Date().toDateString();
    const yesterday = new Date(Date.now() - 86400000).toDateString();
    const dayBefore = new Date(Date.now() - 172800000).toDateString();
    
    sessions.forEach(s => {
        const d = new Date(s.updated_at);
        const ds = d.toDateString();
        let label;
        
        if (ds === today) label = '今天';
        else if (ds === yesterday) label = '昨天';
        else if (ds === dayBefore) label = '前天';
        else label = `${d.getMonth()+1}月${d.getDate()}日 ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
        
        if (!groups[label]) groups[label] = [];
        groups[label].push(s);
    });
    
    return groups;
}

async function loadSession(sessionId) {
    currentSessionId = sessionId;
    
    try {
        const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/messages`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!res.ok) throw new Error('加载失败');
        
        const messages = await res.json();
        const container = document.getElementById('chat-messages');
        container.innerHTML = '';
        
        messages.forEach(msg => {
            if (msg.role === 'user' || msg.role === 'assistant') {
                appendMessage(msg.role, msg.content, msg.mode, msg.id, false);
            }
        });
    } catch (err) {
        console.error('加载会话失败:', err);
    }
}

// ========== 对话 ==========
async function sendMessage() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    
    const mode = 'detailed';
    
    input.value = '';
    
    // 显示用户消息
    appendMessage('user', text, null, null, false);
    
    // 显示加载中
    const loadingId = 'loading-' + Date.now();
    appendMessage('assistant', '<div class="loading"></div>', null, loadingId, false);
    
    try {
        const res = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                session_id: currentSessionId ? String(currentSessionId) : null,
                message: text,
                mode: 'detailed'
            })
        });
        
        // 移除加载中
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();
        
        if (!res.ok) {
            appendMessage('assistant', '抱歉，服务暂时不可用，请稍后重试。', mode, null, false);
            return;
        }
        
        // 处理SSE流
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let assistantContent = '';
        let assistantMessageId = null;
        let messageEl = null;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            
            let event = null;
            let data = null;
            
            for (const line of lines) {
                if (line.startsWith('event:')) {
                    event = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                    data = line.slice(5).trim();
                } else if (line === '' && event && data) {
                    // 处理事件
                    try {
                        const parsed = JSON.parse(data);
                        
                        if (event === 'delta') {
                            // 强制创建 messageEl
                            if (!messageEl) {
                                messageEl = appendMessage('assistant', '', mode, null, true);
                            }
                            if (!messageEl) {
                                console.error('[DELTA] appendMessage returned null');
                                continue;
                            }
                            assistantContent += parsed.content || '';
                            try {
                                messageEl.querySelector('.message-content').innerHTML = marked(assistantContent);
                            } catch (e) {
                                console.error('[marked error]', e);
                                messageEl.querySelector('.message-content').textContent = assistantContent;
                            }
                        } else if (event === 'thought') {
                            const thought = parsed.thought || '';
                            if (!messageEl) {
                                messageEl = appendMessage('assistant', '', mode, null, true);
                            }
                            if (messageEl) {
                                const contentEl = messageEl.querySelector('.message-content');
                                if (contentEl) {
                                    contentEl.textContent = thought;
                                }
                            }
                        } else if (event === 'done') {
                            assistantContent = parsed.content || '';
                            if (!messageEl) {
                                messageEl = appendMessage('assistant', assistantContent, mode, null, false);
                            } else {
                                // 显示最终内容，保留 thought 提示
                                const contentEl = messageEl.querySelector('.message-content');
                                if (contentEl) {
                                    // 先保存 thought 提示
                                    const thoughtEl = contentEl.querySelector('.thought-hint');
                                    try {
                                        contentEl.innerHTML = marked(assistantContent);
                                    } catch (e) {
                                        console.error('[marked error]', e);
                                        contentEl.textContent = assistantContent;
                                    }
                                    // 恢复 thought 提示
                                    if (thoughtEl) {
                                        contentEl.appendChild(thoughtEl);
                                    }
                                }
                            }
                        } else if (event === 'error') {
                            const errorMsg = parsed.error || '抱歉，服务暂时不可用，请稍后重试。';
                            if (messageEl) {
                                messageEl.querySelector('.message-content').innerHTML = marked(errorMsg);
                            } else {
                                appendMessage('assistant', errorMsg, mode, null, false);
                            }
                        } else if (event === 'message_id') {
                            assistantMessageId = parsed.message_id;
                            if (messageEl) {
                                messageEl.dataset.messageId = assistantMessageId;
                                addFeedbackButtons(messageEl, assistantMessageId);
                            }
                        }
                    } catch (e) {
                        // 忽略解析错误
                    }
                    
                    event = null;
                    data = null;
                }
            }
        }
        
        // 刷新历史会话列表
        loadHistory();
        
    } catch (err) {
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();
        appendMessage('assistant', '网络错误，请稍后重试。', mode, null, false);
    }
}

function appendMessage(role, content, mode = '', messageId, isStreaming) {
    const container = document.getElementById('chat-messages');
    if (!container) {
        console.error('[appendMessage] container not found');
        return null;
    }
    const div = document.createElement('div');
    div.className = `message ${role}`;
    if (messageId) {
        div.id = messageId;
        div.dataset.messageId = messageId;
    }
    
    try {
        div.innerHTML = `<div class="message-content">${isStreaming ? '' : marked(content)}</div>`;
    } catch (e) {
        console.error('[appendMessage] innerHTML error:', e);
        div.innerHTML = `<div class="message-content">${content || ''}</div>`;
    }
    
    if (role === 'assistant' && !isStreaming && messageId) {
        addFeedbackButtons(div, messageId);
    }
    
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    
    return div;
}

function addFeedbackButtons(messageEl, messageId) {
    const bar = document.createElement('div');
    bar.className = 'feedback-bar';
    bar.innerHTML = `
        <button onclick="sendFeedback(${messageId}, 1, this)">👍</button>
        <button onclick="sendFeedback(${messageId}, -1, this)">👎</button>
    `;
    messageEl.appendChild(bar);
}

async function sendFeedback(messageId, rating, btn) {
    try {
        const res = await fetch(`${API_BASE}/api/feedback`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ message_id: messageId, rating })
        });
        
        if (res.ok) {
            // 标记已投票
            const bar = btn.parentElement;
            bar.querySelectorAll('button').forEach(b => b.classList.remove('voted'));
            btn.classList.add('voted');
        }
    } catch (err) {
        console.error('反馈失败:', err);
    }
}

// ========== 简易Markdown解析 ==========
function marked(text) {
    if (!text) return '';
    
    let html = text;
    
    // 表格（必须在换行处理之前）
    html = html.replace(/\n\|(.+)\|\n\|([-:\|\s]+)\|\n((?:\|.+\|\n?)+)/g, function(match, header, separator, rows) {
        const headers = header.split('|').map(h => h.trim()).filter(h => h);
        const rowData = rows.trim().split('\n').map(row => {
            return row.split('|').map(c => c.trim()).filter(c => c);
        }).filter(r => r.length > 0);
        
        let tableHtml = '<table class="md-table"><thead><tr>';
        headers.forEach(h => {
            tableHtml += `<th>${h}</th>`;
        });
        tableHtml += '</tr></thead><tbody>';
        
        rowData.forEach(row => {
            tableHtml += '<tr>';
            row.forEach(cell => {
                tableHtml += `<td>${cell}</td>`;
            });
            tableHtml += '</tr>';
        });
        tableHtml += '</tbody></table>';
        
        return tableHtml;
    });
    
    // 标题
    html = html.replace(/### (.*)/g, '<h3>$1</h3>');
    html = html.replace(/## (.*)/g, '<h3>$1</h3>');
    html = html.replace(/# (.*)/g, '<h3>$1</h3>');
    
    // 粗体/斜体
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    
    // 行内代码
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // 列表项（注意：不与表格冲突）
    html = html.replace(/^(?!<table|<thead|<tbody|<tr|<td|<th|<\/table|<\/thead|<\/tbody|<\/tr|<\/td|<\/th)(- (.*))/gm, '<li>$2</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    
    // 分隔线
    html = html.replace(/\n---\n/g, '<hr>');
    
    // 换行
    html = html.replace(/\n/g, '<br>');
    
    return html;
}
