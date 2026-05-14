<template>
  <div class="document-viewer">
    <div class="document-header">
      <h2 class="document-title">{{ document?.title || '未命名文档' }}</h2>
      <div class="document-meta">
        <span class="meta-item">📄 {{ document?.filename }}</span>
        <span v-if="isDocx" class="meta-item format-badge">Word 格式渲染</span>
      </div>
    </div>
    
    <div class="document-body">
      <!-- 注释宿主：所有格式共用，承载锚点/气泡/右键菜单 -->
      <div
        class="annot-host"
        ref="annotHostRef"
        @contextmenu.prevent="onContextMenu"
      >
        <!-- PDF 查看器 -->
        <iframe
          v-if="isPdfIframe"
          :src="`${document.annotated_url}#toolbar=1&view=FitH`"
          class="pdf-viewer"
          ref="pdfIframe"
        ></iframe>

        <!-- 网页HTML查看器：最大限度展示原始界面 -->
        <iframe
          v-else-if="isWebIframe"
          :src="document.annotated_url"
          class="web-viewer"
          sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
          referrerpolicy="no-referrer"
          :style="{ minHeight: '600px' }"
        ></iframe>

        <!-- 网页降级：Word样式格式化展示（无标注URL时） -->
        <div v-else-if="document?.is_web && !document?.annotated_url" class="web-fallback">
          <div class="web-fallback-toolbar">
            <span class="toolbar-icon">🌐</span>
            <span class="toolbar-text">网页内容 · 文档模式展示</span>
          </div>
          <div class="web-fallback-content" v-html="highlightedContent"></div>
        </div>

        <!-- Word 文档：mammoth.js 格式化渲染 -->
        <div v-else-if="isDocx" class="docx-preview">
          <div class="docx-toolbar">
            <div class="docx-toolbar-info">
              <span class="toolbar-icon">📘</span>
              <span class="toolbar-text">Word 文档 · 已保留原始格式</span>
              <span v-if="docxLoading" class="loading-tag">⏳ 渲染中...</span>
              <span v-else-if="docxError" class="error-tag">⚠️ 渲染失败，已降级为文本模式</span>
              <span v-else class="ready-tag">✅ 渲染完成</span>
            </div>
            <button @click="handleDownload" class="download-btn">
              📥 下载标注版文档
            </button>
          </div>
          <div
            v-if="!docxError && docxHtmlContent"
            class="docx-rendered"
            v-html="docxHtmlContent"
          ></div>
          <div v-else class="document-content" v-html="highlightedContent"></div>
        </div>

        <!-- 其他格式预览 -->
        <div v-else class="document-content" v-html="highlightedContent"></div>

        <!-- iframe 格式：批注覆盖层（默认 pointer-events:none，开启批注模式后才接管右键） -->
        <div
          v-if="needsOverlay"
          class="annot-iframe-overlay"
          :class="{ 'is-active': annotMode }"
          @contextmenu.prevent.stop="onContextMenu"
        >
          <span v-if="annotMode" class="overlay-hint">📝 批注模式 · 在任意位置右键添加注释 · 再次点击按钮退出</span>
        </div>

        <!-- 临时注释锚点 + 气泡（始终位于最上层） -->
        <div
          v-for="a in annotations"
          :key="a.id"
          class="annot-anchor"
          :class="{ 'is-open': a.open }"
          :style="{ left: a.x + 'px', top: a.y + 'px' }"
          @click.stop="toggleAnnotation(a.id)"
          @contextmenu.stop.prevent
          :title="a.open ? '点击收起' : '点击展开注释'"
        >
          <span class="annot-sign">{{ a.open ? '−' : '+' }}</span>
          <div
            v-if="a.open"
            class="annot-bubble"
            @click.stop
            @contextmenu.stop.prevent
          >
            <div class="annot-bubble-head">
              <span class="annot-dot"></span>
              <span class="annot-head-text">临时注释 · 仅本次会话</span>
              <button
                class="annot-del-btn"
                title="删除该注释"
                @click.stop="removeAnnotation(a.id)"
              >✕</button>
            </div>
            <textarea
              class="annot-textarea"
              v-model="a.content"
              wrap="off"
              placeholder="在此输入注释…"
              ref="annotTextareas"
            ></textarea>
          </div>
        </div>

        <!-- iframe 格式：批注模式切换按钮（浮于右上角） -->
        <button
          v-if="needsOverlay"
          class="annot-mode-btn"
          :class="{ 'is-active': annotMode }"
          @click.stop="toggleAnnotMode"
          :title="annotMode ? '退出批注模式（恢复 iframe 交互）' : '进入批注模式（接管右键以添加注释）'"
        >
          <span class="mode-icon">📝</span>
          <span class="mode-text">{{ annotMode ? '退出批注' : '批注模式' }}</span>
        </button>
      </div>

      <!-- 右键浮层菜单（fixed 定位，所有格式共用） -->
      <div
        v-if="ctxMenu.show"
        class="annot-ctx-menu"
        :style="{ left: ctxMenu.screenX + 'px', top: ctxMenu.screenY + 'px' }"
        @click.stop
        @contextmenu.stop.prevent
      >
        <button class="annot-ctx-btn" @click="addAnnotationFromMenu">
          <span class="ctx-icon">✎</span>
          <span class="ctx-text">添加注释</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, shallowRef, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import mammoth from 'mammoth'
import { useDocumentStore } from '../stores/document'
import { useToast } from '../composables/useToast.js'

// Store 和 Refs
const documentStore = useDocumentStore()
const toast = useToast()
const pdfIframe = ref(null)
const document = computed(() => documentStore.getCurrentDocument)

// docx mammoth 状态：大 HTML 字符串用 shallowRef 避免深度代理开销
const docxHtmlContent = shallowRef('')
const docxLoading = ref(false)
const docxError = ref(false)

const isDocx = computed(() => {
  const fn = document.value?.filename?.toLowerCase()
  return fn?.endsWith('.docx') || fn?.endsWith('.doc')
})

/**
 * 使用 mammoth.js 将 DOCX 文件转换为带格式的 HTML，然后注入高亮标记
 */
const loadDocxAsHtml = async () => {
  const doc = document.value
  if (!doc || !isDocx.value) return

  const url = doc.annotated_url
  if (!url) {
    // 没有标注版，降级到文本模式
    docxError.value = true
    return
  }

  docxLoading.value = true
  docxError.value = false
  docxHtmlContent.value = ''

  try {
    const response = await fetch(url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const arrayBuffer = await response.arrayBuffer()

    // mammoth 转 HTML，保留语义格式
    const result = await mammoth.convertToHtml(
      { arrayBuffer },
      {
        styleMap: [
          "p[style-name='Heading 1'] => h1:fresh",
          "p[style-name='Heading 2'] => h2:fresh",
          "p[style-name='Heading 3'] => h3:fresh",
          "p[style-name='Heading 4'] => h4:fresh",
          "p[style-name='标题 1']    => h1:fresh",
          "p[style-name='标题 2']    => h2:fresh",
          "p[style-name='标题 3']    => h3:fresh",
          "b => strong",
          "i => em",
          "u => u"
        ]
      }
    )

    let html = result.value

    // ── 对齐格式后处理：用 DOMParser 读取 p.style.textAlign，注入 data-align ──
    // 这比 CSS 属性选择器更可靠，不依赖 mammoth 输出的 style 字符串格式
    {
      const domDoc = new DOMParser().parseFromString(html, 'text/html')
      domDoc.querySelectorAll('p, h1, h2, h3, h4, h5, h6').forEach(el => {
        const align = el.style.textAlign  // 读取浏览器解析后的规范化值
        if (align && align !== 'left') {
          el.dataset.align = align        // 注入 data-align="center" 等
        }
      })
      html = domDoc.body.innerHTML
    }

    // 注入高亮标记（按长度降序，避免短文本覆盖长文本匹配）
    const highlights = [...(doc.highlights || [])].sort(
      (a, b) => (b.text?.length || 0) - (a.text?.length || 0)
    )

    highlights.forEach((hl) => {
      if (!hl.text) return
      const isPoint   = hl.color === '#ff6b6b'
      const bgColor   = `${hl.color}55`
      const border    = isPoint ? `3px solid ${hl.color}` : `2px dotted ${hl.color}`
      const weight    = isPoint ? '600' : '400'

      // 转义正则特殊字符
      const escaped = hl.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      try {
        const regex = new RegExp(`(${escaped})`, 'g')
        html = html.replace(
          regex,
          `<mark class="highlight ${isPoint ? 'highlight-point' : 'highlight-evidence'}" ` +
          `style="background-color:${bgColor};border-bottom:${border};font-weight:${weight}" ` +
          `data-id="${hl.id}">$1</mark>`
        )
      } catch (_) {
        // 正则异常时跳过该条
      }
    })

    docxHtmlContent.value = html
  } catch (e) {
    console.error('[mammoth] 转换失败:', e)
    docxError.value = true
  } finally {
    docxLoading.value = false
  }
}

// 文档切换时重新渲染
watch(document, loadDocxAsHtml, { immediate: true })

// ============ 临时注释（仅前端、切文档/刷新自动清空、覆盖所有格式） ============
const annotHostRef = ref(null)
const annotTextareas = ref([])
const annotations = ref([])
const ctxMenu = reactive({
  show: false,
  screenX: 0,   // 菜单显示坐标（fixed，相对视口）
  screenY: 0,
  targetX: 0,   // 光标在宿主内部坐标（含 scroll）
  targetY: 0
})

// 是否走 iframe（PDF / 网页带标注URL）：iframe 会接管右键，需要叠加 overlay 才能批注
const isPdfIframe = computed(() =>
  document.value?.filename?.toLowerCase().endsWith('.pdf') && !!document.value?.annotated_url
)
const isWebIframe = computed(() =>
  document.value?.is_web && !!document.value?.annotated_url
)
const needsOverlay = computed(() => isPdfIframe.value || isWebIframe.value)

// 批注模式开关：仅 iframe 类型用到（开启后 overlay 拦截右键，关闭后恢复 iframe 正常交互）
const annotMode = ref(false)
const toggleAnnotMode = () => {
  annotMode.value = !annotMode.value
  if (!annotMode.value) ctxMenu.show = false
}

// 切换文档时清空注释 + 重置批注模式（刷新页面由组件重建天然清空）
watch(
  () => document.value?.record_id ?? document.value?.filename ?? null,
  () => {
    annotations.value = []
    ctxMenu.show = false
    annotMode.value = false
  }
)

// 右键：计算内部坐标并展示浮层菜单
const onContextMenu = (e) => {
  const host = annotHostRef.value
  if (!host) return
  const rect = host.getBoundingClientRect()
  ctxMenu.targetX = e.clientX - rect.left + host.scrollLeft
  ctxMenu.targetY = e.clientY - rect.top + host.scrollTop
  // 菜单防越界：右/下边缘留 160×48 空间
  const vw = window.innerWidth, vh = window.innerHeight
  ctxMenu.screenX = Math.min(e.clientX, vw - 160)
  ctxMenu.screenY = Math.min(e.clientY, vh - 52)
  ctxMenu.show = true
}

// 点击"添加注释"：在右键位置插入 + 锚点
const addAnnotationFromMenu = () => {
  annotations.value.push({
    id: Date.now() + Math.random(),
    x: ctxMenu.targetX,
    y: ctxMenu.targetY,
    open: false,
    content: ''
  })
  ctxMenu.show = false
}

// 切换 +/−
const toggleAnnotation = (id) => {
  const item = annotations.value.find(a => a.id === id)
  if (!item) return
  const willOpen = !item.open
  // 只允许同时打开一个气泡
  if (willOpen) annotations.value.forEach(a => { a.open = false })
  item.open = willOpen
  if (willOpen) {
    nextTick(() => {
      const ta = annotTextareas.value?.[annotTextareas.value.length - 1]
      if (ta && typeof ta.focus === 'function') ta.focus()
    })
  }
}

// 删除单条注释
const removeAnnotation = (id) => {
  annotations.value = annotations.value.filter(a => a.id !== id)
}

// 全局点击：关菜单、关所有气泡（锚点/气泡内部已 stopPropagation）
const onGlobalClick = () => {
  ctxMenu.show = false
  annotations.value.forEach(a => { if (a.open) a.open = false })
}
// 全局右键：若目标不在宿主内，关菜单
const onGlobalContextMenu = (e) => {
  const host = annotHostRef.value
  if (!host || !host.contains(e.target)) ctxMenu.show = false
}
onMounted(() => {
  window.addEventListener('click', onGlobalClick)
  window.addEventListener('contextmenu', onGlobalContextMenu)
})
onBeforeUnmount(() => {
  window.removeEventListener('click', onGlobalClick)
  window.removeEventListener('contextmenu', onGlobalContextMenu)
})

// HTML 转义（仅对纯文本段使用，避免源文本里的 & < > 被当成 HTML）
const escapeHtml = (s) => s
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

// 把一段纯文本按换行切成 <p>/<br>
const wrapParagraphs = (plain) => {
  if (!plain) return ''
  const esc = escapeHtml(plain)
  // 一次 replace 完成段落化，比 split+map+join 快 10x
  return '<p>' + esc.replace(/\n/g, '</p><p>') + '</p>'
}

// 生成高亮标注后的内容（纯文本降级 / 非 DOCX 格式使用）
// 性能：O(N+H) 单次遍历，N=文本长度，H=高亮数量
// 相比旧的 O(N*H) substring 复制实现，几万字+几百高亮可从数秒降到 <100ms
const highlightedContent = computed(() => {
  const doc = document.value
  if (!doc || !doc.content) {
    return `<div class="empty-state"><div class="empty-icon">📄</div><p>请上传或选择一个文档进行分析</p></div>`
  }

  const content = doc.content
  const highlights = doc.highlights || []

  // 无高亮快速路径
  if (highlights.length === 0) {
    return wrapParagraphs(content)
  }

  // 升序排序 + 过滤非法区间
  const sorted = []
  for (const hl of highlights) {
    if (hl && typeof hl.start === 'number' && typeof hl.end === 'number' &&
        hl.start >= 0 && hl.end > hl.start && hl.end <= content.length) {
      sorted.push(hl)
    }
  }
  sorted.sort((a, b) => a.start - b.start)

  // 单次遍历构建片段数组（避免 O(N*H) 字符串拼接）
  const parts = []
  let cursor = 0
  for (const hl of sorted) {
    if (hl.start < cursor) continue  // 重叠高亮跳过
    if (hl.start > cursor) {
      parts.push(escapeHtml(content.substring(cursor, hl.start)))
    }
    const isPoint = hl.color === '#ff6b6b'
    const borderStyle = isPoint ? `3px solid ${hl.color}` : `2px dotted ${hl.color}`
    const bgOpacity = isPoint ? '55' : '33'
    const cls = isPoint ? 'highlight highlight-point' : 'highlight highlight-evidence'
    parts.push(
      `<mark class="${cls}" style="background-color:${hl.color}${bgOpacity};border-bottom:${borderStyle};font-weight:${isPoint ? '600' : '400'}" data-id="${hl.id}">` +
      escapeHtml(content.substring(hl.start, hl.end)) +
      `</mark>`
    )
    cursor = hl.end
  }
  if (cursor < content.length) {
    parts.push(escapeHtml(content.substring(cursor)))
  }

  // 段落化：用单次 replace 把 \n 转 </p><p>，比 split/map/join 快很多
  return '<p>' + parts.join('').replace(/\n/g, '</p><p>') + '</p>'
})

// 下载标注版文档（使用 Blob 解决跨域问题）
const handleDownload = async () => {
  if (!document.value?.annotated_url) return
  
  try {
    const response = await fetch(document.value.annotated_url)
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const link = window.document.createElement('a')
    link.href = url
    link.setAttribute('download', `annotated_${document.value.filename}`)
    window.document.body.appendChild(link)
    link.click()
    window.document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('下载失败:', error)
    toast.error('文件下载失败，请检查后端服务是否正常。')
  }
}

// PDF 跳转功能：点击关键点跳转到对应页面
const scrollToHighlight = (highlightId) => {
  const allKps = document.value?.keypoints || []
  const kp = allKps.find(k => k.id === highlightId)
  
  if (kp && kp.page) {
    console.log(`正在跳转至第 ${kp.page} 页, ID: ${highlightId}`)
    const baseUrl = document.value.annotated_url
    const jumpUrl = `${baseUrl}?t=${Date.now()}#page=${kp.page}`
    if (pdfIframe.value) {
      pdfIframe.value.src = jumpUrl
    }
  } else {
    const element = window.document.querySelector(`[data-id="${highlightId}"]`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setTimeout(() => {
        element.classList.add('flash-highlight')
        setTimeout(() => {
          element.classList.remove('flash-highlight')
        }, 2000)
      }, 300)
    }
  }
}

defineExpose({ scrollToHighlight })
</script>

<style scoped>
.document-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.document-header {
  padding: 24px 32px;
  border-bottom: 1px solid #d5cabb;
  background: linear-gradient(to bottom, #f5f1ea, #ede7dc);
}

.document-title {
  font-size: 28px;
  font-weight: 700;
  color: #3a3630;
  margin-bottom: 12px;
}

.document-meta {
  display: flex;
  gap: 12px;
  color: #8a7e72;
  font-size: 14px;
  align-items: center;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.format-badge {
  background: #3a9fd815;
  color: #3a9fd8;
  border: 1px solid #3a9fd840;
  border-radius: 12px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 500;
}

.document-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.pdf-viewer {
  flex: 1;
  min-height: 0;
  width: 100%;
  border: none;
}

.web-viewer {
  flex: 1;
  min-height: 0;
  width: 100%;
  border: none;
  background: #f5f5f0;
}

/* 网页降级：Word样式展示 */
.web-fallback {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.web-fallback-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px;
  background: #ede7dc;
  border-bottom: 1px solid #d5cabb;
  flex-shrink: 0;
  font-size: 14px;
  color: #495057;
}

.web-fallback-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 40px 56px;
  background: #f8f8f5;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 15px;
  line-height: 1.8;
  color: #222;
}

.web-fallback-content :deep(p) {
  margin-bottom: 12px;
}

.web-fallback-content :deep(h1),
.web-fallback-content :deep(h2),
.web-fallback-content :deep(h3) {
  margin: 20px 0 10px;
  color: #1a1a1a;
}

.web-fallback-content :deep(.highlight) {
  padding: 2px 1px;
  cursor: pointer;
  border-radius: 2px;
}

/* ===== DOCX 渲染区 ===== */
.docx-preview {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.docx-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #ede7dc;
  border-bottom: 1px solid #d5cabb;
  flex-shrink: 0;
  gap: 16px;
}

.docx-toolbar-info {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: #495057;
}

.toolbar-icon {
  font-size: 18px;
}

.toolbar-text {
  font-weight: 500;
}

.loading-tag {
  color: #f59e0b;
  font-size: 13px;
}

.error-tag {
  color: #ef4444;
  font-size: 13px;
}

.ready-tag {
  color: #10b981;
  font-size: 13px;
}

.download-btn {
  flex-shrink: 0;
  padding: 8px 20px;
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 6px rgba(58, 159, 216, 0.25);
  white-space: nowrap;
}

.download-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(58, 159, 216, 0.3);
}

/* 注释宿主：所有格式共用容器，承担相对定位以让锚点叠加在任意展示区上 */
.annot-host {
  flex: 1;
  min-height: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f8f8f5;
}

/* iframe 模式覆盖层：默认 pointer-events:none 让 iframe 正常交互；开启批注后接管右键 */
.annot-iframe-overlay {
  position: absolute;
  inset: 0;
  z-index: 5;
  pointer-events: none;
  background: transparent;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.annot-iframe-overlay.is-active {
  pointer-events: auto;
  cursor: crosshair;
  background: rgba(232, 138, 42, 0.04);
  border: 2px dashed rgba(232, 138, 42, 0.55);
}
.overlay-hint {
  position: absolute;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  padding: 6px 14px;
  background: linear-gradient(135deg, #fffdf7, #f5ecd7);
  color: #8a6a3a;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid #d5b878;
  border-radius: 16px;
  box-shadow: 0 4px 12px rgba(120, 90, 40, 0.18);
  pointer-events: none;
  white-space: nowrap;
  letter-spacing: 0.3px;
}

/* 批注模式切换按钮（仅 iframe 格式显示，浮于右上角） */
.annot-mode-btn {
  position: absolute;
  top: 14px;
  right: 16px;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: linear-gradient(135deg, #fffdf7, #f5ecd7);
  color: #5c4a38;
  border: 1px solid #d5b878;
  border-radius: 18px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 3px 10px rgba(120, 90, 40, 0.18);
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease, color 0.15s ease;
  user-select: none;
}
.annot-mode-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(120, 90, 40, 0.25);
}
.annot-mode-btn.is-active {
  background: linear-gradient(135deg, #ffb347, #e88a2a);
  color: #fff;
  border-color: #c06617;
  box-shadow: 0 4px 14px rgba(232, 138, 42, 0.45);
}
.annot-mode-btn .mode-icon {
  font-size: 13px;
  line-height: 1;
}

/* mammoth 渲染内容区 */
.docx-rendered {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 40px 56px;
  background: #f8f8f5;
  font-family: 'Times New Roman', Times, serif;
  font-size: 14pt;
  line-height: 1.8;
  color: #222;
}

/* 还原 Word 常见格式 */
.docx-rendered :deep(h1) {
  font-size: 22pt;
  font-weight: 700;
  margin: 24px 0 12px;
  color: #1a1a1a;
  border-bottom: 2px solid #e5e7eb;
  padding-bottom: 6px;
  text-indent: 0;
}
.docx-rendered :deep(h2) {
  font-size: 18pt;
  font-weight: 700;
  margin: 20px 0 10px;
  color: #222;
  text-indent: 0;
}
.docx-rendered :deep(h3) {
  font-size: 15pt;
  font-weight: 600;
  margin: 16px 0 8px;
  color: #333;
  text-indent: 0;
}
.docx-rendered :deep(h4) {
  font-size: 13pt;
  font-weight: 600;
  margin: 12px 0 6px;
  color: #444;
  text-indent: 0;
}
/* 普通段落默认首行缩进 */
.docx-rendered :deep(p) {
  margin-bottom: 10px;
  text-indent: 2em;
}
/* 居中 / 居右对齐（由 JS 注入 data-align 属性） */
.docx-rendered :deep([data-align="center"]) {
  text-align: center;
  text-indent: 0 !important;
}
.docx-rendered :deep([data-align="right"]) {
  text-align: right;
  text-indent: 0 !important;
}
.docx-rendered :deep([data-align="justify"]) {
  text-align: justify;
  text-indent: 2em;
}
/* 兼容旧的 CSS 属性选择器方式，加 !important 确保生效 */
.docx-rendered :deep(p[style*="text-align"]) {
  text-indent: 0 !important;
}
.docx-rendered :deep(p[style*="text-align: center"]),
.docx-rendered :deep(p[style*="text-align:center"]) {
  text-align: center !important;
  text-indent: 0 !important;
}
.docx-rendered :deep(p[style*="text-align: right"]),
.docx-rendered :deep(p[style*="text-align:right"]) {
  text-align: right !important;
  text-indent: 0 !important;
}
.docx-rendered :deep(p[style*="text-align: justify"]),
.docx-rendered :deep(p[style*="text-align:justify"]) {
  text-align: justify;
  text-indent: 2em;
}
.docx-rendered :deep(strong) {
  font-weight: 700;
}
.docx-rendered :deep(em) {
  font-style: italic;
}
.docx-rendered :deep(u) {
  text-decoration: underline;
}
.docx-rendered :deep(ul),
.docx-rendered :deep(ol) {
  margin: 8px 0 8px 2em;
  padding-left: 1em;
}
.docx-rendered :deep(li) {
  margin-bottom: 4px;
}
.docx-rendered :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 16px 0;
  font-size: 12pt;
}
.docx-rendered :deep(td),
.docx-rendered :deep(th) {
  border: 1px solid #ccc;
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
}
.docx-rendered :deep(th) {
  background: #eee;
  font-weight: 600;
}
.docx-rendered :deep(tr:nth-child(even) td) {
  background: #f0f0ed;
}

/* 高亮标记样式 */
.docx-rendered :deep(.highlight) {
  padding: 2px 1px;
  cursor: pointer;
  transition: all 0.3s;
  border-radius: 2px;
}
.docx-rendered :deep(.highlight-point) {
  box-shadow: 0 2px 4px rgba(255, 107, 107, 0.15);
}
.docx-rendered :deep(.highlight-evidence) {
  box-shadow: 0 1px 3px rgba(81, 207, 102, 0.1);
}
.docx-rendered :deep(.highlight:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0,0,0,0.15) !important;
}
.docx-rendered :deep(.highlight.flash-highlight) {
  animation: flashHighlight 2s ease-in-out;
}

/* 普通文本内容区（非 DOCX 降级模式） */
.document-content {
  flex: 1;
  min-height: 0;
  padding: 32px;
  overflow-y: auto;
  background: #f8f8f5;
  border-radius: 8px;
}

.document-content :deep(p) {
  margin-bottom: 12px;
  line-height: 1.8;
  color: #333;
}

.document-content :deep(.highlight) {
  padding: 3px 2px;
  cursor: pointer;
  transition: all 0.3s;
  border-radius: 3px;
}

.document-content :deep(.highlight-point) {
  box-shadow: 0 2px 4px rgba(255, 107, 107, 0.15);
}

.document-content :deep(.highlight-evidence) {
  box-shadow: 0 1px 3px rgba(81, 207, 102, 0.1);
}

.document-content :deep(.highlight:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0,0,0,0.15) !important;
}

.document-content :deep(.highlight.flash-highlight) {
  animation: flashHighlight 2s ease-in-out;
  transform-origin: center;
}

@keyframes flashHighlight {
  0%   { transform: scale(1);    box-shadow: 0 0 0 rgba(102, 126, 234, 0); }
  20%  { transform: scale(1.05); box-shadow: 0 0 20px rgba(102, 126, 234, 0.6); background-color: rgba(102, 126, 234, 0.3) !important; }
  50%  { transform: scale(1.08); box-shadow: 0 0 30px rgba(102, 126, 234, 0.8); background-color: rgba(102, 126, 234, 0.4) !important; }
  80%  { transform: scale(1.02); box-shadow: 0 0 15px rgba(102, 126, 234, 0.4); }
  100% { transform: scale(1);    box-shadow: 0 0 0 rgba(102, 126, 234, 0); }
}

/* ============ 临时注释：右键菜单 / 锚点 / 气泡 ============ */

/* 右键浮层菜单：简洁米白系 */
.annot-ctx-menu {
  position: fixed;
  z-index: 2000;
  min-width: 148px;
  padding: 6px;
  background: #fffdf7;
  border: 1px solid #e8dcc8;
  border-radius: 10px;
  box-shadow: 0 12px 28px rgba(92, 74, 56, 0.18), 0 3px 8px rgba(92, 74, 56, 0.08);
  animation: annotMenuIn 0.12s ease-out;
}
@keyframes annotMenuIn {
  from { opacity: 0; transform: translateY(-4px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0)    scale(1); }
}
.annot-ctx-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 14px;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  color: #5c4a38;
  font-size: 13px;
  font-weight: 500;
  transition: background 0.15s, color 0.15s;
  text-align: left;
}
.annot-ctx-btn:hover {
  background: linear-gradient(135deg, #fdf6e6 0%, #f5ecd7 100%);
  color: #3a2a18;
}
.annot-ctx-btn .ctx-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb347, #e88a2a);
  color: #fff;
  font-size: 12px;
  box-shadow: 0 2px 4px rgba(232, 138, 42, 0.35);
}

/* +/− 锚点：小巧圆形，居中符号 */
.annot-anchor {
  position: absolute;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb347 0%, #e88a2a 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transform: translate(-50%, -50%);
  box-shadow: 0 3px 8px rgba(232, 138, 42, 0.45), 0 1px 2px rgba(0,0,0,0.08);
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
  z-index: 20;
  user-select: none;
}
.annot-anchor:hover {
  transform: translate(-50%, -50%) scale(1.1);
  box-shadow: 0 5px 14px rgba(232, 138, 42, 0.6), 0 2px 4px rgba(0,0,0,0.12);
}
.annot-anchor.is-open {
  background: linear-gradient(135deg, #e88a2a 0%, #c06617 100%);
  z-index: 30;
}
.annot-sign {
  font-family: 'Segoe UI', system-ui, sans-serif;
  font-size: 16px;
  font-weight: 700;
  line-height: 1;
  display: block;
  text-align: center;
}

/* 气泡：长 7×一号字 ≈ 243px，宽 5×一号字 ≈ 173px，以锚点居中向上弹出 */
.annot-bubble {
  position: absolute;
  bottom: calc(100% + 12px);
  left: 50%;
  transform: translateX(-50%);
  width: 243px;
  height: 173px;
  background: linear-gradient(135deg, #fffdf7 0%, #fdf6e6 55%, #f5ecd7 100%);
  border: 1px solid #d5b878;
  border-radius: 12px;
  box-shadow:
    0 14px 32px rgba(120, 90, 40, 0.22),
    0 4px 10px rgba(120, 90, 40, 0.10),
    inset 0 1px 0 rgba(255,255,255,0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  cursor: default;
  animation: annotBubbleIn 0.18s cubic-bezier(0.2, 0.9, 0.3, 1.2);
}
@keyframes annotBubbleIn {
  from { opacity: 0; transform: translateX(-50%) translateY(6px) scale(0.94); }
  to   { opacity: 1; transform: translateX(-50%) translateY(0)    scale(1); }
}
/* 气泡底部指向锚点的小三角 */
.annot-bubble::before,
.annot-bubble::after {
  content: '';
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 0;
  border-left: 8px solid transparent;
  border-right: 8px solid transparent;
}
.annot-bubble::before {
  bottom: -8px;
  border-top: 8px solid #d5b878;
}
.annot-bubble::after {
  bottom: -7px;
  border-top: 8px solid #f5ecd7;
}

/* 气泡头部：独特装饰条 + 关闭按钮 */
.annot-bubble-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: linear-gradient(90deg, rgba(232,138,42,0.14) 0%, rgba(232,138,42,0) 100%);
  border-bottom: 1px solid rgba(213, 184, 120, 0.5);
  font-size: 11px;
  color: #8a6a3a;
  font-weight: 600;
  letter-spacing: 0.3px;
}
.annot-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: linear-gradient(135deg, #ffb347, #e88a2a);
  flex-shrink: 0;
}
.annot-head-text {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.annot-del-btn {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border: none;
  background: transparent;
  color: #8a6a3a;
  cursor: pointer;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.annot-del-btn:hover {
  background: rgba(232, 138, 42, 0.18);
  color: #c92a2a;
}

/* textarea：wrap=off + overflow:auto 实现左右和上下滚动 */
.annot-textarea {
  flex: 1;
  width: 100%;
  padding: 8px 10px;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.65;
  color: #3a2a18;
  white-space: pre;        /* 配合 wrap="off" 禁止自动换行 */
  overflow: auto;          /* 横向/纵向双向滚动 */
  scrollbar-width: thin;
  scrollbar-color: #d5b878 transparent;
}
.annot-textarea::placeholder {
  color: #b8a07c;
  font-style: italic;
}
.annot-textarea::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.annot-textarea::-webkit-scrollbar-thumb {
  background: #d5b878;
  border-radius: 3px;
}
.annot-textarea::-webkit-scrollbar-track {
  background: transparent;
}
</style>
