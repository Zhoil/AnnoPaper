<template>
  <div class="chat-container">
    <!-- 头部信息 -->
    <div class="chat-header">
      <div class="chat-header-left">
        <span class="chat-model-icon">🤖</span>
        <div>
          <div class="chat-title">AI 助手</div>
          <div class="chat-subtitle">DeepSeek-R1 驱动 · 联动当前页面</div>
        </div>
      </div>
      <button class="clear-btn" @click="clearChat" title="清空对话">
        🗑️
      </button>
    </div>

    <!-- 文档上下文提示 -->
    <div v-if="hasDocument" class="doc-context-badge">
      <span class="doc-badge-icon">📄</span>
      <span class="doc-badge-text">已载入文档：{{ documentTitle }}</span>
    </div>
    <div v-else class="doc-context-badge no-doc">
      <span class="doc-badge-icon">⚠️</span>
      <span class="doc-badge-text">暂无文档，上传文档后可获得更精准的问答</span>
    </div>

    <!-- 消息列表 -->
    <div class="chat-messages" ref="messagesContainer">
      <!-- 欢迎消息 -->
      <div v-if="messages.length === 0" class="welcome-msg">
        <div class="welcome-icon">💬</div>
        <p class="welcome-text">你好！我是你的 AI 阅读助手</p>
        <p class="welcome-hint">{{ hasDocument ? '我已阅读当前文档，可以回答你关于文档的问题。' : '上传文档后，我能结合文档内容为你提供深度解析。' }}</p>
        <div class="suggest-btns" v-if="hasDocument">
          <button class="suggest-btn" @click="sendSuggest('请总结这篇文档的核心内容')">📋 总结核心内容</button>
          <button class="suggest-btn" @click="sendSuggest('这篇文档最重要的论点是什么？')">🎯 最重要的论点</button>
          <button class="suggest-btn" @click="sendSuggest('这篇文档有哪些值得深思的观点？')">💡 值得深思的观点</button>
        </div>
      </div>

      <!-- 聊天气泡 -->
      <TransitionGroup name="msg">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="message-wrapper"
          :class="msg.role"
        >
          <div class="message-avatar">
            <span v-if="msg.role === 'user'">👤</span>
            <span v-else>🤖</span>
          </div>
          <div class="message-bubble" :class="{ 'md-bubble': msg.role === 'assistant' }">
            <div class="message-content" v-html="formatMessage(msg.content, msg.role)"></div>
            <div class="message-time">{{ msg.time }}</div>
          </div>
        </div>
      </TransitionGroup>

      <!-- 加载中 -->
      <div v-if="isLoading" class="message-wrapper assistant">
        <div class="message-avatar"><span>🤖</span></div>
        <div class="message-bubble loading-bubble">
          <div class="typing-dots">
            <span></span><span></span><span></span>
          </div>
          <div class="loading-text">思考中...</div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input-area">
      <textarea
        v-model="inputText"
        class="chat-input"
        placeholder="输入问题，按 Enter 发送，Shift+Enter 换行..."
        :disabled="isLoading"
        @keydown.enter.exact.prevent="sendMessage"
        @keydown.shift.enter.exact="() => {}"
        rows="2"
      ></textarea>
      <button
        class="send-btn"
        :class="{ loading: isLoading }"
        :disabled="isLoading || !inputText.trim()"
        @click="sendMessage"
      >
        <span v-if="!isLoading">发送</span>
        <span v-else class="spinner">⏳</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { marked } from 'marked'
import { useDocumentStore } from '../stores/document'

const documentStore = useDocumentStore()
const messagesContainer = ref(null)
const inputText = ref('')
const isLoading = ref(false)
const messages = ref([])
let messageId = 0

const hasDocument = computed(() => documentStore.hasDocument)
const documentTitle = computed(() => documentStore.getCurrentDocument?.title || '当前文档')

// 配置 marked 渲染选项
marked.setOptions({
  breaks: true,      // 换行符转为 <br>
  gfm: true,         // 启用 GitHub Flavored Markdown
})

// 文档切换时清空对话
watch(() => documentStore.getCurrentDocument?.record_id, () => {
  clearChat()
})

const formatTime = () => {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// 用户消息：转义 HTML，换行转 <br>
const formatUserMessage = (text) => {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

// AI 消息：用 marked 渲染 markdown
const formatAssistantMessage = (text) => {
  try {
    return marked.parse(text)
  } catch (e) {
    // 降级处理
    return text.replace(/\n/g, '<br>')
  }
}

const formatMessage = (content, role) => {
  if (role === 'assistant') {
    return formatAssistantMessage(content)
  }
  return formatUserMessage(content)
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

const clearChat = () => {
  messages.value = []
  inputText.value = ''
}

const sendSuggest = (text) => {
  inputText.value = text
  sendMessage()
}

const sendMessage = async () => {
  const text = inputText.value.trim()
  if (!text || isLoading.value) return

  // 添加用户消息
  messages.value.push({
    id: ++messageId,
    role: 'user',
    content: text,
    time: formatTime()
  })
  inputText.value = ''
  await scrollToBottom()

  isLoading.value = true

  // 构建发送给 API 的历史记录（只传 role + content）
  const chatHistory = messages.value
    .slice(0, -1)  // 排除刚加入的用户消息
    .map(m => ({ role: m.role, content: m.content }))

  try {
    const response = await documentStore.sendChatMessage(text, chatHistory)

    messages.value.push({
      id: ++messageId,
      role: 'assistant',
      content: response,
      time: formatTime()
    })
  } catch (error) {
    messages.value.push({
      id: ++messageId,
      role: 'assistant',
      content: `⚠️ 发生错误：${error.message}`,
      time: formatTime()
    })
  } finally {
    isLoading.value = false
    await scrollToBottom()
  }
}
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 500px;
}

/* 头部 */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid #d5cabb;
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-model-icon {
  font-size: 28px;
}

.chat-title {
  font-size: 15px;
  font-weight: 700;
  color: #3a3630;
}

.chat-subtitle {
  font-size: 11px;
  color: #3a9fd8;
  font-weight: 500;
}

.clear-btn {
  background: rgba(58, 159, 216, 0.06);
  border-radius: 8px;
  width: 32px;
  height: 32px;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  cursor: pointer;
  color: #8a7e72;
}

.clear-btn:hover {
  background: rgba(255,100,100,0.1);
  color: #ff6b6b;
}

/* 文档上下文 badge */
.doc-context-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, rgba(58,159,216,0.06), rgba(58,159,216,0.03));
  border: 1px solid rgba(58,159,216,0.15);
  border-radius: 8px;
  padding: 6px 10px;
  margin-bottom: 10px;
}

.doc-context-badge.no-doc {
  background: rgba(192,144,96,0.06);
  border-color: rgba(192,144,96,0.15);
}

.doc-badge-icon {
  font-size: 13px;
  flex-shrink: 0;
}

.doc-badge-text {
  font-size: 11px;
  color: #8a7e72;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.no-doc .doc-badge-text {
  color: #a08a6e;
}

/* 消息区域 */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
  margin-bottom: 10px;
  min-height: 300px;
  max-height: 420px;
}

.chat-messages::-webkit-scrollbar {
  width: 4px;
}

.chat-messages::-webkit-scrollbar-thumb {
  background: #c9bfb0;
  border-radius: 4px;
}

/* 欢迎区域 */
.welcome-msg {
  text-align: center;
  padding: 20px 10px;
  color: #8a7e72;
}

.welcome-icon {
  font-size: 36px;
  margin-bottom: 10px;
}

.welcome-text {
  font-size: 14px;
  font-weight: 600;
  color: #3a3630;
  margin-bottom: 6px;
}

.welcome-hint {
  font-size: 12px;
  color: #95a5a6;
  margin-bottom: 16px;
}

.suggest-btns {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.suggest-btn {
  padding: 8px 12px;
  background: linear-gradient(135deg, rgba(58,159,216,0.06), rgba(58,159,216,0.03));
  border: 1px solid rgba(58,159,216,0.15);
  border-radius: 10px;
  color: #3a9fd8;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
}

.suggest-btn:hover {
  background: linear-gradient(135deg, #6db8e3, #3a9fd8);
  color: white;
  border-color: transparent;
  transform: translateX(2px);
}

/* 消息气泡 */
.message-wrapper {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  animation: fadeIn 0.3s ease;
}

.message-wrapper.user {
  flex-direction: row-reverse;
}

.message-avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
  background: rgba(58, 159, 216, 0.04);
}

.message-wrapper.user .message-avatar {
  background: linear-gradient(135deg, #6db8e3, #3a9fd8);
}

.message-bubble {
  max-width: 82%;
  padding: 10px 14px;
  border-radius: 16px;
  line-height: 1.6;
  position: relative;
}

.message-wrapper.user .message-bubble {
  background: linear-gradient(135deg, #6db8e3, #3a9fd8);
  color: white;
  border-bottom-right-radius: 4px;
}

.message-wrapper.assistant .message-bubble {
  background: #f5f1ea;
  color: #3a3630;
  border-bottom-left-radius: 4px;
  border: 1px solid #d5cabb;
}

.message-content {
  font-size: 13px;
  word-break: break-word;
}

/* AI 消息 markdown 渲染样式 */
.md-bubble :deep(.message-content) {
  line-height: 1.7;
}

.md-bubble :deep(p) {
  margin: 0 0 8px 0;
}

.md-bubble :deep(p:last-child) {
  margin-bottom: 0;
}

.md-bubble :deep(h1),
.md-bubble :deep(h2),
.md-bubble :deep(h3),
.md-bubble :deep(h4) {
  font-weight: 700;
  margin: 10px 0 6px 0;
  color: #3a3630;
}

.md-bubble :deep(h1) { font-size: 16px; }
.md-bubble :deep(h2) { font-size: 15px; }
.md-bubble :deep(h3) { font-size: 14px; }

.md-bubble :deep(ul),
.md-bubble :deep(ol) {
  margin: 6px 0 6px 20px;
  padding: 0;
}

.md-bubble :deep(li) {
  margin: 3px 0;
}

.md-bubble :deep(strong) {
  font-weight: 700;
  color: #3a3630;
}

.md-bubble :deep(em) {
  font-style: italic;
  color: #5a6fa8;
}

.md-bubble :deep(code) {
  background: rgba(58, 159, 216, 0.08);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  color: #d63384;
}

.md-bubble :deep(pre) {
  background: #1e2229;
  border-radius: 8px;
  padding: 12px;
  margin: 8px 0;
  overflow-x: auto;
}

.md-bubble :deep(pre code) {
  background: transparent;
  color: #abb2bf;
  padding: 0;
  font-size: 12px;
  line-height: 1.5;
}

.md-bubble :deep(blockquote) {
  border-left: 3px solid #667eea;
  margin: 8px 0;
  padding: 4px 12px;
  background: rgba(58,159,216,0.06);
  border-radius: 0 6px 6px 0;
  color: #8a7e72;
  font-style: italic;
}

.md-bubble :deep(hr) {
  border: none;
  border-top: 1px solid rgba(58,159,216,0.1);
  margin: 10px 0;
}

.md-bubble :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 12px;
}

.md-bubble :deep(th),
.md-bubble :deep(td) {
  border: 1px solid rgba(255,255,255,0.1);
  padding: 6px 10px;
  text-align: left;
}

.md-bubble :deep(th) {
  background: rgba(58, 159, 216, 0.04);
  font-weight: 700;
}

.md-bubble :deep(a) {
  color: #667eea;
  text-decoration: none;
}

.md-bubble :deep(a:hover) {
  text-decoration: underline;
}

.message-time {
  font-size: 10px;
  opacity: 0.6;
  margin-top: 4px;
  text-align: right;
}

/* 加载动画 */
.loading-bubble {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
}

.typing-dots {
  display: flex;
  gap: 4px;
}

.typing-dots span {
  width: 7px;
  height: 7px;
  background: #3a9fd8;
  border-radius: 50%;
  animation: bounce 1.2s infinite;
}

.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-6px); }
}

.loading-text {
  font-size: 12px;
  color: #95a5a6;
}

/* 输入区域 */
.chat-input-area {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding-top: 10px;
  border-top: 1px solid #d5cabb;
}

.chat-input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid #d5cabb;
  border-radius: 12px;
  font-size: 13px;
  resize: none;
  transition: border-color 0.2s ease;
  font-family: inherit;
  line-height: 1.5;
  color: #3a3630;
  background: #ffffff;
}

.chat-input:focus {
  border-color: #667eea;
  outline: none;
  box-shadow: 0 0 0 3px rgba(58, 159, 216, 0.1);
}

.chat-input:disabled {
  background: #ede7dc;
  color: #b0a494;
}

.send-btn {
  width: 60px;
  height: 60px;
  border-radius: 12px;
  background: linear-gradient(135deg, #6db8e3, #3a9fd8);
  color: white;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
  cursor: pointer;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(58, 159, 216, 0.35);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinner {
  animation: spin 1s linear infinite;
  display: inline-block;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 过渡动画 */
.msg-enter-active {
  transition: all 0.3s ease;
}

.msg-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
