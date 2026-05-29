<template>
  <!-- 全屏时 Teleport 到 body，覆盖整个视口 -->
  <Teleport to="body" :disabled="!isFullscreen">
  <div class="chat-container" :class="{ fullscreen: isFullscreen }">
    <!-- 头部信息 -->
    <div class="chat-header">
      <div class="chat-header-left">
        <span class="chat-model-icon">🤖</span>
        <div>
          <div class="chat-title">AI 助手</div>
          <div class="chat-subtitle">DeepSeek-V4 驱动 · 联动当前页面 · 基于轻量RAG</div>
        </div>
      </div>
      <div class="chat-header-actions">
        <button class="header-action-btn" @click="toggleFullscreen" :title="isFullscreen ? '退出全屏' : '全屏模式'">
          <span v-if="!isFullscreen">⛶</span>
          <span v-else>✕</span>
        </button>
        <button class="clear-btn" @click="clearChat" title="清空对话">
          🗑️
        </button>
      </div>
    </div>

    <!-- 文档上下文提示 + RAG 模式切换 + 深度思考开关 -->
    <div v-if="hasDocument" class="doc-context-badge">
      <span class="doc-badge-icon">📄</span>
      <span class="doc-badge-text">已载入文档：{{ documentTitle }}</span>
      <label class="rag-switch" :title="'开启后强制将文档全文传给 AI，适合总结与全局性问题'">
        <input type="checkbox" v-model="fullScan" />
        <span class="rag-switch-label">全文模式</span>
      </label>
      <button
        class="thinking-toggle-btn"
        :class="{ active: deepThinking }"
        @click="deepThinking = !deepThinking"
        title="开启后 AI 将展示详细思考过程"
      >
        <span class="thinking-toggle-icon">🧠</span>
        <span class="thinking-toggle-text">Thinking</span>
      </button>
    </div>
    <div v-else class="doc-context-badge no-doc">
      <span class="doc-badge-icon">⚠️</span>
      <span class="doc-badge-text">暂无文档，上传文档后可获得更精准的问答</span>
      <button
        class="thinking-toggle-btn"
        :class="{ active: deepThinking }"
        @click="deepThinking = !deepThinking"
        title="开启后 AI 将展示详细思考过程"
      >
        <span class="thinking-toggle-icon">🧠</span>
        <span class="thinking-toggle-text">Thinking</span>
      </button>
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
            <!-- 思考面板 -->
            <div v-if="msg.thinking" class="thinking-panel">
              <div class="thinking-header" @click="toggleThinking(msg)">
                <span class="thinking-icon">🧠</span>
                <span class="thinking-label">Thinking</span>
                <span v-if="msg.isStreaming && !msg.thinkingDone" class="thinking-status">思考中...</span>
                <span v-else-if="msg.thinkingDone" class="thinking-status done">已完成</span>
                <span class="thinking-arrow" :class="{ expanded: msg._thinkExpanded }">▾</span>
              </div>
              <transition name="think-expand">
                <div v-show="msg._thinkExpanded" class="thinking-body">
                  <div class="thinking-text" v-html="renderThinking(msg)"></div>
                  <span v-if="msg.isStreaming && !msg.thinkingDone" class="streaming-cursor"></span>
                </div>
              </transition>
            </div>
            <!-- 正式回答 -->
            <div class="message-content" v-html="renderMessage(msg)"></div>
            <span v-if="msg.isStreaming && msg.thinkingDone" class="streaming-cursor"></span>
            <div class="message-time">{{ msg.time }}</div>
          </div>
        </div>
      </TransitionGroup>

      <!-- 加载中（仅在等待首个 chunk 时显示） -->
      <div v-if="isLoading && !streamingMsg" class="message-wrapper assistant">
        <div class="message-avatar"><span>🤖</span></div>
        <div class="message-bubble loading-bubble">
          <div class="typing-dots">
            <span></span><span></span><span></span>
          </div>
          <div class="loading-text">{{ deepThinking ? '正在深度思考...' : '思考中...' }}</div>
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
  </Teleport>
</template>

<script setup>
import { ref, computed, nextTick, watch, onBeforeUnmount } from 'vue'
import { marked } from 'marked'
import { useDocumentStore } from '../stores/document'

const documentStore = useDocumentStore()
const messagesContainer = ref(null)
const inputText = ref('')
const isLoading = ref(false)
const messages = ref([])
const deepThinking = ref(true)
const isFullscreen = ref(false)
const streamingMsg = ref(null) // 当前正在流式接收的消息引用
let messageId = 0

// 全屏切换
const toggleFullscreen = () => {
  isFullscreen.value = !isFullscreen.value
  // 全屏时禁止 body 滚动
  document.body.style.overflow = isFullscreen.value ? 'hidden' : ''
}

// ESC 退出全屏
const onKeydown = (e) => {
  if (e.key === 'Escape' && isFullscreen.value) {
    toggleFullscreen()
  }
}
document.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})

const hasDocument = computed(() => documentStore.hasDocument)
const documentTitle = computed(() => documentStore.getCurrentDocument?.title || '当前文档')
const fullScan = ref(false)

// 配置 marked 渲染选项
marked.setOptions({
  breaks: true,
  gfm: true,
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
  if (!text) return ''
  try {
    return marked.parse(text)
  } catch (e) {
    return text.replace(/\n/g, '<br>')
  }
}

// 渲染消息：带缓存避免重复解析
const renderMessage = (msg) => {
  if (!msg) return ''
  if (msg.role === 'user') {
    if (msg._html !== undefined) return msg._html
    msg._html = formatUserMessage(msg.content || '')
    return msg._html
  }
  // assistant 消息：流式接收中不缓存（内容持续变化）
  if (msg.isStreaming) {
    return formatAssistantMessage(msg.content || '')
  }
  if (msg._html !== undefined) return msg._html
  msg._html = formatAssistantMessage(msg.content || '')
  return msg._html
}

// 渲染思考内容（简单换行处理，不做复杂 markdown）
const renderThinking = (msg) => {
  if (!msg || !msg.thinking) return ''
  if (msg.isStreaming && !msg.thinkingDone) {
    // 流式中不缓存
    return msg.thinking.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
  }
  if (msg._thinkHtml !== undefined) return msg._thinkHtml
  msg._thinkHtml = msg.thinking.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
  return msg._thinkHtml
}

// 思考面板展开/收起
const toggleThinking = (msg) => {
  msg._thinkExpanded = !msg._thinkExpanded
}

// 自动滚动（仅在用户未手动上滑时触发）
let userScrolledUp = false
const onScroll = () => {
  const el = messagesContainer.value
  if (!el) return
  userScrolledUp = el.scrollTop + el.clientHeight < el.scrollHeight - 50
}

const scrollToBottom = async () => {
  if (userScrolledUp) return
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

const clearChat = () => {
  messages.value = []
  inputText.value = ''
  streamingMsg.value = null
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

  // 构建历史记录
  const chatHistory = messages.value
    .filter(m => !m.isStreaming)
    .slice(-10)
    .map(m => ({ role: m.role, content: m.content }))

  // 创建空 AI 消息占位
  const aiMsg = {
    id: ++messageId,
    role: 'assistant',
    content: '',
    thinking: '',
    time: formatTime(),
    isStreaming: true,
    thinkingDone: false,
    _thinkExpanded: true, // 默认展开思考面板
  }
  messages.value.push(aiMsg)
  streamingMsg.value = aiMsg
  await scrollToBottom()

  // RAF 缓冲：合并高频更新，每帧最多刷新一次
  let thinkingBuffer = ''
  let contentBuffer = ''
  let rafId = null

  const flushBuffers = () => {
    const hadThinking = !!thinkingBuffer
    if (thinkingBuffer) {
      aiMsg.thinking += thinkingBuffer
      thinkingBuffer = ''
      delete aiMsg._thinkHtml
    }
    if (contentBuffer) {
      aiMsg.content += contentBuffer
      contentBuffer = ''
      delete aiMsg._html
    }
    // 触发响应式更新（浅触发）
    messages.value = [...messages.value]
    scrollToBottom()
    // 思考面板自动滚动到底部
    if (hadThinking && aiMsg._thinkExpanded) {
      nextTick(() => {
        const el = messagesContainer.value
        if (!el) return
        const thinkBody = el.querySelector('.thinking-body')
        if (thinkBody) {
          thinkBody.scrollTop = thinkBody.scrollHeight
        }
      })
    }
    rafId = null
  }

  const scheduleFlush = () => {
    if (!rafId) {
      rafId = requestAnimationFrame(flushBuffers)
    }
  }

  try {
    await documentStore.sendChatMessageStream(
      text,
      chatHistory,
      {
        ragMode: fullScan.value ? 'full' : 'auto',
        deepThinking: deepThinking.value,
      },
      {
        onMeta(data) {
          // 可接收 rag_mode 等元信息
        },
        onThinking(textPiece) {
          thinkingBuffer += textPiece
          scheduleFlush()
        },
        onContent(textPiece) {
          // 首次收到 content 时，标记思考阶段结束并自动收起
          if (!aiMsg.thinkingDone && aiMsg.thinking) {
            aiMsg.thinkingDone = true
            aiMsg._thinkExpanded = false
            delete aiMsg._thinkHtml
          }
          contentBuffer += textPiece
          scheduleFlush()
        },
        onDone(data) {
          // 确保缓冲区全部刷新
          if (rafId) {
            cancelAnimationFrame(rafId)
            rafId = null
          }
          flushBuffers()
          aiMsg.isStreaming = false
          aiMsg.thinkingDone = true
          if (!aiMsg.thinking) {
            // 没有思考内容则不显示面板
          }
          // 追加 RAG 标签
          if (data?.rag_mode === 'full') {
            aiMsg.content += '\n\n<small style="opacity:0.55">✨ 已采用全文模式进行回答</small>'
          } else if (data?.rag_mode === 'retrieve') {
            aiMsg.content += '\n\n<small style="opacity:0.55">🔍 已基于相关片段检索回答</small>'
          }
          delete aiMsg._html
          messages.value = [...messages.value]
        },
        onError(msg) {
          if (rafId) {
            cancelAnimationFrame(rafId)
            rafId = null
          }
          flushBuffers()
          aiMsg.isStreaming = false
          aiMsg.thinkingDone = true
          if (!aiMsg.content) {
            aiMsg.content = `⚠️ ${msg}`
          }
          delete aiMsg._html
          messages.value = [...messages.value]
        }
      }
    )
  } catch (error) {
    aiMsg.isStreaming = false
    aiMsg.content = `⚠️ 发生错误：${error.message}`
    delete aiMsg._html
    messages.value = [...messages.value]
  } finally {
    isLoading.value = false
    streamingMsg.value = null
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

/* 全屏模式 */
.chat-container.fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  background: #faf8f5;
  min-height: unset;
  padding: 0;
  border-radius: 0;
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

.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.header-action-btn {
  background: rgba(58, 159, 216, 0.06);
  border-radius: 8px;
  width: 32px;
  height: 32px;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  cursor: pointer;
  color: #8a7e72;
  border: none;
}

.header-action-btn:hover {
  background: rgba(58, 159, 216, 0.15);
  color: #3a9fd8;
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
  border: none;
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
  flex-wrap: wrap;
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

.rag-switch {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(58,159,216,0.08);
  border: 1px solid rgba(58,159,216,0.2);
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.rag-switch:hover {
  background: rgba(58,159,216,0.15);
  border-color: rgba(58,159,216,0.35);
}

.rag-switch input {
  cursor: pointer;
  accent-color: #3a9fd8;
}

.rag-switch-label {
  font-size: 11px;
  color: #3a9fd8;
  font-weight: 600;
  user-select: none;
}

/* 深度思考开关按钮 */
.thinking-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 12px;
  background: rgba(120, 120, 120, 0.08);
  border: 1px solid rgba(120, 120, 120, 0.2);
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.25s ease;
  font-size: 11px;
  color: #8a7e72;
  font-weight: 600;
}

.thinking-toggle-btn:hover {
  background: rgba(102, 126, 234, 0.12);
  border-color: rgba(102, 126, 234, 0.35);
  color: #667eea;
}

.thinking-toggle-btn.active {
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.15), rgba(118, 75, 226, 0.12));
  border-color: rgba(102, 126, 234, 0.4);
  color: #667eea;
  box-shadow: 0 0 8px rgba(102, 126, 234, 0.15);
}

.thinking-toggle-icon {
  font-size: 12px;
}

.thinking-toggle-text {
  user-select: none;
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

.fullscreen .chat-messages {
  max-height: unset;
  min-height: unset;
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

/* 思考面板 */
.thinking-panel {
  margin-bottom: 10px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.06), rgba(118, 75, 226, 0.04));
  border: 1px solid rgba(102, 126, 234, 0.15);
  overflow: hidden;
}

.thinking-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}

.thinking-header:hover {
  background: rgba(102, 126, 234, 0.08);
}

.thinking-icon {
  font-size: 13px;
}

.thinking-label {
  font-size: 12px;
  font-weight: 600;
  color: #667eea;
}

.thinking-status {
  font-size: 11px;
  color: #95a5a6;
  margin-left: 4px;
}

.thinking-status.done {
  color: #51cf66;
}

.thinking-arrow {
  margin-left: auto;
  font-size: 12px;
  color: #667eea;
  transition: transform 0.3s ease;
}

.thinking-arrow.expanded {
  transform: rotate(0deg);
}

.thinking-arrow:not(.expanded) {
  transform: rotate(-90deg);
}

.thinking-body {
  padding: 0 12px 10px 12px;
  max-height: 200px;
  overflow-y: auto;
  border-top: 1px solid rgba(102, 126, 234, 0.1);
}

.thinking-body::-webkit-scrollbar {
  width: 3px;
}

.thinking-body::-webkit-scrollbar-thumb {
  background: rgba(102, 126, 234, 0.2);
  border-radius: 3px;
}

.thinking-text {
  font-size: 12px;
  line-height: 1.7;
  color: #6b7280;
  padding-top: 8px;
  word-break: break-word;
}

/* 流式光标 */
.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 14px;
  background: #667eea;
  margin-left: 2px;
  vertical-align: text-bottom;
  animation: blink 0.8s infinite;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 思考面板展开/收起过渡 */
.think-expand-enter-active,
.think-expand-leave-active {
  transition: all 0.3s ease;
  max-height: 200px;
  overflow: hidden;
}

.think-expand-enter-from,
.think-expand-leave-to {
  max-height: 0;
  opacity: 0;
  padding-top: 0;
  padding-bottom: 0;
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
  border: none;
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

/* ============ 全屏模式专属样式（类 DeepSeek 网页端） ============ */
.fullscreen .chat-header {
  padding: 16px 40px 14px;
  margin-bottom: 0;
  border-bottom: 1px solid #e8e0d4;
  background: #faf8f5;
}

.fullscreen .chat-model-icon {
  font-size: 34px;
}

.fullscreen .chat-title {
  font-size: 18px;
}

.fullscreen .chat-subtitle {
  font-size: 13px;
}

.fullscreen .header-action-btn {
  width: 38px;
  height: 38px;
  font-size: 20px;
}

.fullscreen .clear-btn {
  width: 38px;
  height: 38px;
  font-size: 16px;
}

.fullscreen .doc-context-badge {
  margin: 0 auto 0;
  padding: 10px 20px;
  max-width: 800px;
  width: 100%;
  border-radius: 0;
  border-left: none;
  border-right: none;
  border-top: none;
  background: linear-gradient(135deg, rgba(58,159,216,0.04), rgba(58,159,216,0.02));
}

.fullscreen .doc-badge-text {
  font-size: 13px;
}

.fullscreen .rag-switch-label {
  font-size: 12px;
}

.fullscreen .thinking-toggle-btn {
  font-size: 13px;
  padding: 4px 14px;
  border-radius: 14px;
}

.fullscreen .chat-messages {
  padding: 30px 0;
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
}

.fullscreen .welcome-icon {
  font-size: 50px;
  margin-bottom: 16px;
}

.fullscreen .welcome-text {
  font-size: 20px;
  margin-bottom: 10px;
}

.fullscreen .welcome-hint {
  font-size: 15px;
  margin-bottom: 24px;
}

.fullscreen .suggest-btn {
  font-size: 14px;
  padding: 12px 18px;
}

.fullscreen .message-wrapper {
  margin-bottom: 24px;
}

.fullscreen .message-avatar {
  width: 38px;
  height: 38px;
  font-size: 20px;
}

.fullscreen .message-bubble {
  max-width: 720px;
  padding: 16px 22px;
  border-radius: 18px;
}

.fullscreen .message-content {
  font-size: 15px;
  line-height: 1.75;
}

.fullscreen .message-time {
  font-size: 11px;
}

.fullscreen .thinking-panel {
  margin-bottom: 14px;
}

.fullscreen .thinking-header {
  padding: 10px 16px;
}

.fullscreen .thinking-label {
  font-size: 14px;
}

.fullscreen .thinking-text {
  font-size: 13px;
  line-height: 1.8;
}

.fullscreen .thinking-body {
  max-height: 360px;
  padding: 0 16px 14px 16px;
}

.fullscreen .chat-input-area {
  max-width: 800px;
  width: 100%;
  margin: 0 auto;
  padding: 16px 0 24px;
  border-top: 1px solid #e8e0d4;
}

.fullscreen .chat-input {
  font-size: 15px;
  padding: 14px 18px;
  border-radius: 16px;
  min-height: 52px;
}

.fullscreen .send-btn {
  width: 68px;
  height: 68px;
  border-radius: 16px;
  font-size: 16px;
}

/* 全屏 markdown 字体放大 */
.fullscreen .md-bubble :deep(h1) { font-size: 20px; }
.fullscreen .md-bubble :deep(h2) { font-size: 18px; }
.fullscreen .md-bubble :deep(h3) { font-size: 16px; }
.fullscreen .md-bubble :deep(code) { font-size: 13px; }
.fullscreen .md-bubble :deep(pre code) { font-size: 13px; }
.fullscreen .md-bubble :deep(table) { font-size: 14px; }
</style>
