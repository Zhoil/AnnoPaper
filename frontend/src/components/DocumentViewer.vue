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
      <!-- PDF 查看器 -->
      <iframe 
        v-if="document?.filename?.toLowerCase().endsWith('.pdf') && document?.annotated_url" 
        :src="`${document.annotated_url}#toolbar=1&view=FitH`" 
        class="pdf-viewer" 
        ref="pdfIframe"
      ></iframe>
      
      <!-- 网页HTML查看器：最大限度展示原始界面 -->
      <iframe 
        v-else-if="document?.is_web && document?.annotated_url"
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

        <!-- mammoth 渲染结果 -->
        <div 
          v-if="!docxError && docxHtmlContent"
          class="docx-rendered"
          v-html="docxHtmlContent"
        ></div>

        <!-- 降级：纯文本显示 -->
        <div v-else class="document-content" v-html="highlightedContent"></div>
      </div>
      
      <!-- 其他格式预览 -->
      <div v-else class="document-content" v-html="highlightedContent"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import mammoth from 'mammoth'
import { useDocumentStore } from '../stores/document'
import { useToast } from '../composables/useToast.js'

// Store 和 Refs
const documentStore = useDocumentStore()
const toast = useToast()
const pdfIframe = ref(null)
const document = computed(() => documentStore.getCurrentDocument)

// docx mammoth 状态
const docxHtmlContent = ref('')
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

// 生成高亮标注后的内容（纯文本降级 / 非 DOCX 格式使用）
const highlightedContent = computed(() => {
  if (!document.value || !document.value.content) {
    return `<div class="empty-state"><div class="empty-icon">📄</div><p>请上传或选择一个文档进行分析</p></div>`
  }
  
  let content = document.value.content
  const highlights = document.value.highlights || []
  
  // 按位置倒序排序，避免插入时位置偏移
  const sortedHighlights = [...highlights].sort((a, b) => b.start - a.start)
  
  // 插入高亮标记：论点(红色实线) vs 论据(蓝绿虚线)
  sortedHighlights.forEach((hl) => {
    const before = content.substring(0, hl.start)
    const text = content.substring(hl.start, hl.end)
    const after = content.substring(hl.end)
    
    const isPoint = hl.color === '#ff6b6b'
    const borderStyle = isPoint ? `3px solid ${hl.color}` : `2px dotted ${hl.color}`
    const bgOpacity = isPoint ? '55' : '33'
    
    content = before + 
      `<mark class="highlight ${isPoint ? 'highlight-point' : 'highlight-evidence'}" style="background-color: ${hl.color}${bgOpacity}; border-bottom: ${borderStyle}; font-weight: ${isPoint ? '600' : '400'}" data-id="${hl.id}">` + 
      text + 
      `</mark>` + 
      after
  })
  
  return content.split('\n').map(line => line.trim() ? `<p>${line}</p>` : '<br>').join('')
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
</style>
