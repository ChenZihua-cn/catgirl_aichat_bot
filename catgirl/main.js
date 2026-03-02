// 猫娘桌面助手 - 主要JavaScript逻辑
class CatgirlAssistant {
    constructor() {
        this.isChatOpen = false;
        this.isTyping = false;
        this.isDragging = false;
        this.dragOffset = { x: 0, y: 0 };
        this.messageHistory = [];
        this.ollamaConnected = false;
        this.currentModel = 'llama2';
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.setupDragAndDrop();
        this.checkOllamaConnection();
        this.loadSettings();
        this.showWelcomeMessage();
    }
    
    setupEventListeners() {
        // 猫娘头像点击事件
        const catgirlAvatar = document.getElementById('catgirlAvatar');
        catgirlAvatar.addEventListener('click', () => this.toggleChat());
        
        // 发送按钮事件
        const sendButton = document.getElementById('sendButton');
        sendButton.addEventListener('click', () => this.sendMessage());
        
        // 输入框回车事件
        const messageInput = document.getElementById('messageInput');
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
        
        // 输入框自动调整高度
        messageInput.addEventListener('input', () => {
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 80) + 'px';
        });
        
        // 全局键盘快捷键
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && e.key === 'm') {
                e.preventDefault();
                this.toggleChat();
            }
        });
        
        // 点击外部关闭聊天窗口
        document.addEventListener('click', (e) => {
            const catgirlContainer = document.getElementById('catgirlContainer');
            const chatBubble = document.getElementById('chatBubble');
            
            if (this.isChatOpen && 
                !catgirlContainer.contains(e.target) && 
                !chatBubble.contains(e.target)) {
                this.closeChat();
            }
        });
    }
    
    setupDragAndDrop() {
        const catgirlContainer = document.getElementById('catgirlContainer');
        
        catgirlContainer.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('catgirl-avatar')) {
                this.isDragging = true;
                const rect = catgirlContainer.getBoundingClientRect();
                this.dragOffset.x = e.clientX - rect.left;
                this.dragOffset.y = e.clientY - rect.top;
                catgirlContainer.style.cursor = 'grabbing';
            }
        });
        
        document.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                const x = e.clientX - this.dragOffset.x;
                const y = e.clientY - this.dragOffset.y;
                
                // 边界检查
                const maxX = window.innerWidth - catgirlContainer.offsetWidth;
                const maxY = window.innerHeight - catgirlContainer.offsetHeight;
                
                catgirlContainer.style.left = Math.max(0, Math.min(x, maxX)) + 'px';
                catgirlContainer.style.top = Math.max(0, Math.min(y, maxY)) + 'px';
                catgirlContainer.style.right = 'auto';
                catgirlContainer.style.bottom = 'auto';
            }
        });
        
        document.addEventListener('mouseup', () => {
            this.isDragging = false;
            catgirlContainer.style.cursor = 'move';
        });
    }
    
    toggleChat() {
        if (this.isChatOpen) {
            this.closeChat();
        } else {
            this.openChat();
        }
    }
    
    openChat() {
        const chatBubble = document.getElementById('chatBubble');
        const catgirlAvatar = document.getElementById('catgirlAvatar');
        
        this.isChatOpen = true;
        chatBubble.classList.add('active');
        
        // 猫娘表情变化动画
        catgirlAvatar.classList.add('expression-change');
        setTimeout(() => {
            catgirlAvatar.classList.remove('expression-change');
        }, 600);
        
        // 聚焦输入框
        setTimeout(() => {
            document.getElementById('messageInput').focus();
        }, 300);
        
        this.saveSettings();
    }
    
    closeChat() {
        const chatBubble = document.getElementById('chatBubble');
        
        this.isChatOpen = false;
        chatBubble.classList.remove('active');
        this.saveSettings();
    }
    
    async sendMessage() {
        const messageInput = document.getElementById('messageInput');
        const message = messageInput.value.trim();
        
        if (!message || this.isTyping) return;
        
        // 添加用户消息到界面
        this.addMessage(message, 'user');
        messageInput.value = '';
        messageInput.style.height = 'auto';
        
        // 显示正在输入状态
        this.showTypingIndicator();
        
        try {
            // 调用Ollama API
            const response = await this.callOllamaAPI(message);
            this.hideTypingIndicator();
            this.addMessage(response, 'assistant');
        } catch (error) {
            console.error('调用Ollama API失败:', error);
            this.hideTypingIndicator();
            this.addMessage('抱歉，我暂时无法回复。请检查Ollama连接。', 'assistant');
        }
    }
    
    addMessage(text, sender) {
        const messageContainer = document.getElementById('messageContainer');
        const messageDiv = document.createElement('div');
        
        messageDiv.className = `message-bubble ${sender === 'user' ? 'user-message' : ''} fade-in`;
        messageDiv.textContent = text;
        
        messageContainer.appendChild(messageDiv);
        
        // 保存到历史记录
        this.messageHistory.push({
            text: text,
            sender: sender,
            timestamp: new Date()
        });
        
        // 滚动到底部
        messageContainer.scrollTop = messageContainer.scrollHeight;
        
        // 限制历史记录数量
        if (this.messageHistory.length > 100) {
            this.messageHistory = this.messageHistory.slice(-50);
        }
        
        // 触发猫娘表情变化
        if (sender === 'user') {
            const catgirlAvatar = document.getElementById('catgirlAvatar');
            catgirlAvatar.classList.add('expression-change');
            setTimeout(() => {
                catgirlAvatar.classList.remove('expression-change');
            }, 600);
        }
    }
    
    showTypingIndicator() {
        this.isTyping = true;
        const indicator = document.querySelector('.typing-indicator').parentElement;
        indicator.style.display = 'flex';
    }
    
    hideTypingIndicator() {
        this.isTyping = false;
        const indicator = document.querySelector('.typing-indicator').parentElement;
        indicator.style.display = 'none';
    }
    
    async callOllamaAPI(message) {
        const response = await fetch('http://localhost:11434/api/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                model: this.currentModel,
                prompt: message,
                stream: false,
                options: {
                    temperature: 0.7,
                    top_p: 0.9,
                    max_tokens: 512
                }
            })
        });
        
        if (!response.ok) {
            throw new Error('Ollama API调用失败');
        }
        
        const data = await response.json();
        return data.response || '抱歉，我没有理解你的问题。';
    }
    
    async checkOllamaConnection() {
        const statusIndicator = document.getElementById('statusIndicator');
        
        try {
            const response = await fetch('http://localhost:11434/api/tags');
            if (response.ok) {
                this.ollamaConnected = true;
                statusIndicator.style.background = '#10b981'; // 绿色
                
                // 获取可用模型列表
                const data = await response.json();
                console.log('可用模型:', data.models);
            } else {
                throw new Error('连接失败');
            }
        } catch (error) {
            this.ollamaConnected = false;
            statusIndicator.style.background = '#ef4444'; // 红色
            console.warn('Ollama连接失败，请确保Ollama正在运行');
        }
    }
    
    showWelcomeMessage() {
        const welcomeMessages = [
            '你好呀！我是你的猫娘助手～今天有什么可以帮助你的吗？',
            '喵～主人你好！我是你的专属AI助手，快来和我聊天吧！',
            '嗨！我是你的猫娘朋友，有什么想问我的吗？',
            '欢迎回来！今天也要开开心心地度过哦～',
            '你好！我是你的智能助手，随时准备帮助你！'
        ];
        
        const randomMessage = welcomeMessages[Math.floor(Math.random() * welcomeMessages.length)];
        
        setTimeout(() => {
            this.addMessage(randomMessage, 'assistant');
        }, 1000);
    }
    
    saveSettings() {
        const settings = {
            position: {
                left: document.getElementById('catgirlContainer').style.left,
                top: document.getElementById('catgirlContainer').style.top
            },
            chatOpen: this.isChatOpen,
            messageHistory: this.messageHistory,
            currentModel: this.currentModel
        };
        
        localStorage.setItem('catgirlAssistantSettings', JSON.stringify(settings));
    }
    
    loadSettings() {
        const saved = localStorage.getItem('catgirlAssistantSettings');
        if (saved) {
            const settings = JSON.parse(saved);
            
            // 恢复位置
            if (settings.position.left && settings.position.top) {
                const container = document.getElementById('catgirlContainer');
                container.style.left = settings.position.left;
                container.style.top = settings.position.top;
                container.style.right = 'auto';
                container.style.bottom = 'auto';
            }
            
            // 恢复聊天状态
            if (settings.chatOpen) {
                this.openChat();
            }
            
            // 恢复消息历史
            if (settings.messageHistory) {
                this.messageHistory = settings.messageHistory;
            }
            
            // 恢复模型设置
            if (settings.currentModel) {
                this.currentModel = settings.currentModel;
            }
        }
    }
    
    // 模型切换功能
    switchModel(modelName) {
        this.currentModel = modelName;
        this.saveSettings();
        this.addMessage(`已切换到 ${modelName} 模型`, 'system');
    }
    
    // 清理功能
    clearChat() {
        const messageContainer = document.getElementById('messageContainer');
        messageContainer.innerHTML = '';
        this.messageHistory = [];
        this.saveSettings();
    }
    
    // 导出对话历史
    exportChat() {
        const chatData = {
            messages: this.messageHistory,
            exportTime: new Date().toISOString(),
            model: this.currentModel
        };
        
        const blob = new Blob([JSON.stringify(chatData, null, 2)], {
            type: 'application/json'
        });
        
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `catgirl-chat-${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        
        URL.revokeObjectURL(url);
    }
}

// 全局函数
function toggleChat() {
    window.catgirlAssistant.toggleChat();
}

function openSettings() {
    window.open('settings.html', '_blank');
}

function openModelConfig() {
    window.open('model-config.html', '_blank');
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.catgirlAssistant = new CatgirlAssistant();
    
    // 隐藏打字指示器初始状态
    document.querySelector('.typing-indicator').parentElement.style.display = 'none';
    
    console.log('猫娘桌面助手已启动！');
});

// 窗口大小改变时重新定位
window.addEventListener('resize', () => {
    const container = document.getElementById('catgirlContainer');
    const rect = container.getBoundingClientRect();
    
    // 边界检查
    const maxX = window.innerWidth - container.offsetWidth;
    const maxY = window.innerHeight - container.offsetHeight;
    
    if (rect.left > maxX || rect.top > maxY) {
        container.style.left = Math.min(rect.left, maxX) + 'px';
        container.style.top = Math.min(rect.top, maxY) + 'px';
    }
});

// 页面卸载时保存设置
window.addEventListener('beforeunload', () => {
    if (window.catgirlAssistant) {
        window.catgirlAssistant.saveSettings();
    }
});