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
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useDocumentStore } from '../stores/document'

const documentStore = useDocumentStore()

const summary = computed(() => {
  const doc = documentStore.getCurrentDocument
  return doc?.summary || {}
})

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
</style>
