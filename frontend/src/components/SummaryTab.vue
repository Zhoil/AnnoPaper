<template>
  <div class="summary-tab">
    <div class="summary-header">
      <h3 class="section-title">摘要报告</h3>
    </div>
    
    <div class="summary-sections">
      <!-- 核心观点 -->
      <div class="summary-section">
        <div class="section-header">
          <span class="section-icon">💡</span>
          <h4 class="section-subtitle">核心观点</h4>
        </div>
        <div class="section-content">
          <div v-if="corePoints.length > 0" class="content-list">
            <div v-for="(item, index) in corePoints" :key="index" class="content-item">
              <span class="item-bullet">•</span>
              <span class="item-text">{{ item }}</span>
            </div>
          </div>
          <div v-else class="empty-state">暂无核心观点</div>
        </div>
      </div>

      <!-- 关键数据：卡片网格 -->
      <div class="summary-section">
        <div class="section-header">
          <span class="section-icon">📈</span>
          <h4 class="section-subtitle">关键数据</h4>
        </div>
        <div class="section-content">
          <div v-if="keyDataItems.length > 0" class="data-grid">
            <div v-for="(item, index) in keyDataItems" :key="index" class="data-card">
              <div class="data-value">{{ item.value || '--' }}</div>
              <div class="data-label">{{ item.label || '指标' }}</div>
              <div v-if="item.context" class="data-context">{{ item.context }}</div>
              <div v-if="item.page" class="data-page">第 {{ item.page }} 页</div>
            </div>
          </div>
          <div v-else class="empty-state">本文档未提取到定量数据</div>
        </div>
      </div>

      <!-- 结论总结 -->
      <div class="summary-section">
        <div class="section-header">
          <span class="section-icon">✅</span>
          <h4 class="section-subtitle">结论总结</h4>
        </div>
        <div class="section-content">
          <div v-if="conclusions.length > 0" class="content-list">
            <div v-for="(item, index) in conclusions" :key="index" class="content-item">
              <span class="item-bullet">•</span>
              <span class="item-text">{{ item }}</span>
            </div>
          </div>
          <div v-else class="empty-state">暂无结论总结</div>
        </div>
      </div>

      <!-- 相关文献推荐 -->
      <div class="summary-section recommend-section">
        <div class="section-header recommend-header">
          <span class="section-icon">📚</span>
          <h4 class="section-subtitle">相关文献推荐</h4>
          <button
            class="recommend-btn"
            :disabled="!recordId || recommendLoading || cooldownActive"
            @click="loadRecommendations(false)"
          >
            <span v-if="recommendLoading">加载中…</span>
            <span v-else-if="cooldownActive">冷却中 {{ cooldownSeconds }}s</span>
            <span v-else-if="recommendations.results.length">🔄 查看推荐</span>
            <span v-else>🔍 获取推荐</span>
          </button>
          <button
            v-if="recommendations.results.length && !cooldownActive"
            class="recommend-btn recommend-btn-ghost"
            :disabled="recommendLoading || cooldownActive"
            @click="loadRecommendations(true)"
            title="忽略缓存重新调用大模型生成"
          >
            强制刷新
          </button>
        </div>
        <div class="section-content">
          <div v-if="recommendations.query" class="recommend-query">
            检索关键词：<span>{{ recommendations.query }}</span>
            <span v-if="sourcesText" class="recommend-sources">· {{ sourcesText }}</span>
            <span v-if="cacheBadge" class="recommend-cache-badge" :class="cacheBadgeClass">{{ cacheBadge }}</span>
          </div>
          <div v-if="recommendations.warning" class="recommend-warning">⚠️ {{ recommendations.warning }}</div>
           <div v-if="recommendations.results.length" class="recommend-scroll">
            <div
              class="recommend-track"
              :style="trackStyle"
              @mouseenter="pauseScroll = true"
              @mouseleave="pauseScroll = false"
            >
              <a
                v-for="(item, idx) in doubledResults"
                :key="idx + '-' + (item.external_id || item.title)"
                :href="item.url"
                target="_blank"
                rel="noopener noreferrer"
                class="recommend-card"
              >
                <div class="recommend-card-top">
                  <span class="recommend-source-tag" :class="`source-${item.source}`">
                    {{ sourceLabel(item.source) }}
                  </span>
                  <span v-if="item.year" class="recommend-year">{{ item.year }}</span>
                </div>
                <div class="recommend-title">{{ item.title }}</div>
                <div v-if="item.authors" class="recommend-authors">{{ item.authors }}</div>
                <div v-if="item.venue" class="recommend-venue">{{ item.venue }}</div>
                <div v-if="item.reason" class="recommend-reason">💡 {{ item.reason }}</div>
                <div class="recommend-summary">{{ item.summary }}</div>
                <div class="recommend-link-hint">点击跳转 ↗</div>
              </a>
            </div>
          </div>
          <div v-else-if="recommendLoading" class="empty-state">正在调用大模型检索并验证文献…</div>
          <div v-else-if="!recordId" class="empty-state">请先加载或上传一篇文档</div>
          <div v-else class="empty-state">点击上方“获取推荐”获取相关文献</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useDocumentStore } from '../stores/document'

const documentStore = useDocumentStore()
const { recommendations, recommendLoading } = storeToRefs(documentStore)

const summary = computed(() => {
  const doc = documentStore.getCurrentDocument
  return doc?.summary || {}
})

const recordId = computed(() => {
  const doc = documentStore.getCurrentDocument
  return doc?.record_id || doc?.id || null
})

// sources 新结构：llm_total / arxiv_verified / doi_verified / openalex_verified / wikipedia_verified / news_verified / dropped / genre。
// 同时兼容旧结构 arxiv / semantic_scholar。
const GENRE_LABEL = {
  academic_paper: '学术论文',
  review_paper: '综述论文',
  technical_report: '技术报告',
  news_report: '新闻报道',
  opinion_essay: '评论文章',
  research_report: '研究报告',
  popular_science: '科普文章',
  general: '通用文本'
}
const sourcesText = computed(() => {
  const s = recommendations.value.sources || {}
  const parts = []
  if (s.genre && GENRE_LABEL[s.genre]) parts.push(`文体 ${GENRE_LABEL[s.genre]}`)
  if (typeof s.llm_total === 'number') parts.push(`LLM 候选 ${s.llm_total}`)
  if (typeof s.arxiv_verified === 'number' && s.arxiv_verified) parts.push(`arXiv 验证 ${s.arxiv_verified}`)
  if (typeof s.doi_verified === 'number' && s.doi_verified) parts.push(`DOI 验证 ${s.doi_verified}`)
  if (typeof s.openalex_verified === 'number' && s.openalex_verified) parts.push(`OpenAlex 验证 ${s.openalex_verified}`)
  if (typeof s.wikipedia_verified === 'number' && s.wikipedia_verified) parts.push(`维基 验证 ${s.wikipedia_verified}`)
  if (typeof s.news_verified === 'number' && s.news_verified) parts.push(`新闻 验证 ${s.news_verified}`)
  if (typeof s.dropped === 'number' && s.dropped) parts.push(`丢弃 ${s.dropped}`)
  if (!parts.length) {
    if (s.arxiv) parts.push(`arXiv ${s.arxiv}`)
    if (s.semantic_scholar) parts.push(`Semantic Scholar ${s.semantic_scholar}`)
  }
  return parts.join(' / ')
})

const cacheBadge = computed(() => {
  if (!recommendations.value.fromCache) return ''
  if (recommendations.value.cacheReason === 'click_throttle') return '冷却期直读缓存'
  if (recommendations.value.cacheReason === 'ttl_hit') return '缓存命中（2天内）'
  return '缓存'
})

const cacheBadgeClass = computed(() => {
  return recommendations.value.cacheReason === 'click_throttle' ? 'cache-throttle' : 'cache-hit'
})

// 客户端冷却倒计时，跟着后端 cooldown_remaining 滑动
const cooldownSeconds = ref(0)
let cooldownTimer = null

function startCooldown(sec) {
  if (cooldownTimer) clearInterval(cooldownTimer)
  cooldownSeconds.value = sec
  cooldownTimer = setInterval(() => {
    cooldownSeconds.value -= 1
    if (cooldownSeconds.value <= 0) {
      clearInterval(cooldownTimer)
      cooldownTimer = null
      cooldownSeconds.value = 0
    }
  }, 1000)
}

const cooldownActive = computed(() => cooldownSeconds.value > 0)

onUnmounted(() => {
  if (cooldownTimer) clearInterval(cooldownTimer)
})

function sourceLabel(src) {
  const m = {
    arxiv: 'arXiv',
    semantic_scholar: 'S2',
    openalex: 'OpenAlex',
    wikipedia: '维基',
    news: '新闻',
    gdelt: 'GDELT',
    crossref: 'Crossref'
  }
  return m[src] || src || 'paper'
}

async function loadRecommendations(force = false) {
  if (!recordId.value || cooldownActive.value) return
  await documentStore.fetchRecommendations(recordId.value, 8, { force })
  // 读后端返回的 cooldown_remaining 启动本地倒计时
  const remaining = recommendations.value.cooldownRemaining || 0
  if (remaining > 0) startCooldown(remaining)
  else startCooldown(10)  // 成功调用也触发 10s 前端冷却
}

const corePoints = computed(() => summary.value.core_points || [])

const keyDataItems = computed(() => {
  const raw = summary.value.key_data || []
  return raw.map(item => {
    if (typeof item === 'string') {
      return { label: '数据', value: cleanNumericStr(item), context: '', page: null }
    }
    return {
      ...item,
      value: cleanNumericStr(item.value),
      label: cleanNumericStr(item.label)
    }
  })
})

// 修复数字中的多余空格，如 "0 . 1" -> "0.1"、"94 . 5 %" -> "94.5%"
function cleanNumericStr(str) {
  if (!str) return str
  // 合并数字和小数点之间的空格: "0 . 1" -> "0.1"
  let s = String(str).replace(/(\d)\s+\.\s+(\d)/g, '$1.$2')
  // 合并数字和百分号之间的空格: "94.5 %" -> "94.5%"
  s = s.replace(/(\d)\s+(%)/g, '$1$2')
  // 合并连续数字之间的多余空格: "1 2 3" -> "123"
  s = s.replace(/(\d)\s+(\d)/g, '$1$2')
  // 再次处理（多个连续数字片段）
  s = s.replace(/(\d)\s+(\d)/g, '$1$2')
  return s
}

const conclusions = computed(() => {
  const raw = summary.value.conclusions || []
  return raw.filter(c => c && c.trim())
})

// ── 垂直自动循环滚动 ──
// DOM 中把 results 复制一份，配合 translateY(-50%) 形成 seamless loop
const doubledResults = computed(() => {
  const arr = recommendations.value.results || []
  return arr.length ? [...arr, ...arr] : []
})

const pauseScroll = ref(false)

// 根据条目数量动态调整速度：每条约 4s
const trackStyle = computed(() => {
  const n = (recommendations.value.results || []).length
  const duration = Math.max(18, n * 4)  // 至少 18s，保证视觉舒适
  return {
    animationDuration: `${duration}s`,
    animationPlayState: pauseScroll.value ? 'paused' : 'running'
  }
})
</script>

<style scoped>
.summary-tab {
  animation: fadeIn 0.5s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.summary-header {
  margin-bottom: 24px;
}

.section-title {
  font-size: 20px;
  font-weight: 700;
  color: #3a3630;
}

.summary-sections {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.summary-section {
  background: linear-gradient(135deg, #f5f1ea 0%, #ffffff 100%);
  border-radius: 12px;
  padding: 20px;
  border-left: 4px solid #3a9fd8;
  animation: slideInUp 0.5s ease;
}

@keyframes slideInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.section-icon {
  font-size: 24px;
}

.section-subtitle {
  font-size: 18px;
  font-weight: 600;
  color: #3a3630;
}

.section-content {
  font-size: 14px;
  color: #495057;
  line-height: 1.8;
}

.data-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.data-card {
  background: linear-gradient(135deg, rgba(58,159,216,0.08) 0%, rgba(58,159,216,0.04) 100%);
  border: 1px solid rgba(58,159,216,0.15);
  border-radius: 10px;
  padding: 16px 14px;
  text-align: center;
  transition: all 0.2s;
}

.data-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(58, 159, 216, 0.1);
}

.data-value {
  font-size: 22px;
  font-weight: 700;
  color: #3a9fd8;
  margin-bottom: 4px;
  word-break: break-all;
}

.data-label {
  font-size: 13px;
  font-weight: 600;
  color: #495057;
  margin-bottom: 4px;
}

.data-context {
  font-size: 11px;
  color: #8a7e72;
  line-height: 1.4;
}

.data-page {
  font-size: 10px;
  color: #b0a494;
  margin-top: 4px;
}

.content-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.content-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.item-bullet {
  color: #3a9fd8;
  font-weight: 700;
  font-size: 18px;
  line-height: 1.5;
}

.item-text {
  flex: 1;
  line-height: 1.6;
}

.empty-state {
  color: #8a7e72;
  font-style: italic;
  text-align: center;
  padding: 20px;
}

/* ── 相关文献推荐 ── */
.recommend-section {
  border-left: 4px solid #b07f5b;
  background: linear-gradient(135deg, #fbf6ee 0%, #ffffff 100%);
}

.recommend-header {
  justify-content: flex-start;
  gap: 10px;
}

.recommend-btn {
  margin-left: auto;
  padding: 6px 14px;
  background: linear-gradient(135deg, #b07f5b 0%, #8b6240 100%);
  color: white;
  border: none;
  border-radius: 18px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(176, 127, 91, 0.3);
  transition: all 0.2s ease;
}

.recommend-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(176, 127, 91, 0.4);
}

.recommend-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.recommend-query {
  font-size: 12px;
  color: #8a7e72;
  margin-bottom: 12px;
  padding: 6px 10px;
  background: rgba(176, 127, 91, 0.06);
  border-radius: 8px;
}

.recommend-query span {
  color: #b07f5b;
  font-weight: 600;
}

.recommend-sources {
  margin-left: 6px;
  color: #8a7e72 !important;
  font-weight: 500 !important;
}

.recommend-cache-badge {
  margin-left: 10px;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.recommend-cache-badge.cache-hit {
  background: rgba(88, 168, 120, 0.15);
  color: #3f8857;
  border: 1px solid rgba(88, 168, 120, 0.35);
}

.recommend-cache-badge.cache-throttle {
  background: rgba(216, 162, 58, 0.15);
  color: #a87820;
  border: 1px solid rgba(216, 162, 58, 0.35);
}

.recommend-warning {
  font-size: 12px;
  color: #a85b2b;
  background: rgba(216, 108, 58, 0.08);
  padding: 6px 10px;
  border-radius: 8px;
  margin-bottom: 10px;
}

.recommend-btn-ghost {
  margin-left: 8px !important;
  background: #ffffff !important;
  color: #b07f5b !important;
  border: 1px solid #b07f5b !important;
  box-shadow: none !important;
}

.recommend-btn-ghost:hover:not(:disabled) {
  background: rgba(176, 127, 91, 0.08) !important;
}

.recommend-reason {
  font-size: 11px;
  color: #6a7a6f;
  background: rgba(88, 168, 120, 0.08);
  padding: 4px 8px;
  border-radius: 6px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── 垂直自动循环滚动容器 ── */
.recommend-scroll {
  position: relative;
  height: 420px;
  overflow: hidden;
  padding: 8px 4px;
  mask-image: linear-gradient(to bottom, transparent 0, #000 16px, #000 calc(100% - 16px), transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 16px, #000 calc(100% - 16px), transparent 100%);
}

.recommend-track {
  display: flex;
  flex-direction: column;
  gap: 12px;
  animation-name: recommendScrollUp;
  animation-timing-function: linear;
  animation-iteration-count: infinite;
  will-change: transform;
}

@keyframes recommendScrollUp {
  from { transform: translateY(0); }
  to   { transform: translateY(-50%); }
}

.recommend-card {
  flex: 0 0 auto;
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  background: #ffffff;
  border: 1px solid #e8dcc8;
  border-radius: 12px;
  text-decoration: none;
  color: inherit;
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
  box-shadow: 0 2px 6px rgba(192, 144, 96, 0.05);
}

.recommend-card:hover {
  box-shadow: 0 10px 24px rgba(176, 127, 91, 0.18);
  border-color: #b07f5b;
}

.recommend-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.recommend-source-tag {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.source-arxiv {
  background: linear-gradient(135deg, #b31b1b 0%, #d63b3b 100%);
  color: white;
}

.source-semantic_scholar {
  background: linear-gradient(135deg, #1857b6 0%, #3a78d8 100%);
  color: white;
}

.source-openalex {
  background: linear-gradient(135deg, #0a7a62 0%, #1aa886 100%);
  color: white;
}

.source-wikipedia {
  background: linear-gradient(135deg, #4a4a4a 0%, #6a6a6a 100%);
  color: white;
}

.source-news {
  background: linear-gradient(135deg, #a85b2b 0%, #d87a3a 100%);
  color: white;
}

.source-gdelt {
  background: linear-gradient(135deg, #6b4fb2 0%, #9575d8 100%);
  color: white;
}

.source-crossref {
  background: linear-gradient(135deg, #2b6cb0 0%, #4a90e2 100%);
  color: white;
}

.recommend-year {
  font-size: 11px;
  color: #8a7e72;
  font-weight: 600;
}

.recommend-title {
  font-size: 14px;
  font-weight: 700;
  color: #3a3630;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.recommend-authors {
  font-size: 11px;
  color: #8a7e72;
  font-style: italic;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.recommend-venue {
  font-size: 11px;
  color: #b07f5b;
  font-weight: 600;
}

.recommend-summary {
  font-size: 12px;
  color: #495057;
  line-height: 1.55;
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.recommend-link-hint {
  font-size: 11px;
  color: #b07f5b;
  font-weight: 600;
  margin-top: 4px;
  text-align: right;
}
</style>
