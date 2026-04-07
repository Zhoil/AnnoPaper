<template>
  <div class="statistics-tab">
    <div class="statistics-header">
      <h3 class="section-title">统计信息</h3>
    </div>
    
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon">📝</div>
        <div class="stat-label">总字数</div>
        <div class="stat-value">{{ statistics.word_count || 0 }}</div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon">⭐</div>
        <div class="stat-label">关键点数</div>
        <div class="stat-value">{{ statistics.keypoint_count || 0 }}</div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon">📊</div>
        <div class="stat-label">平均重要性</div>
        <div class="stat-value">{{ statistics.avg_importance || 0 }}</div>
      </div>
    </div>
    
    <div class="category-distribution" v-if="categoryData.length > 0">
      <h4 class="subsection-title">类别分布</h4>
      <div class="category-list">
        <div 
          v-for="cat in categoryData" 
          :key="cat.name"
          class="category-item"
        >
          <div class="category-info">
            <span class="category-name">{{ cat.name }}</span>
            <span class="category-count">{{ cat.count }}</span>
          </div>
          <div class="category-bar">
            <div 
              class="category-bar-fill"
              :style="{ 
                width: `${(cat.count / totalKeypoints) * 100}%`,
                backgroundColor: getCategoryColor(cat.name)
              }"
            ></div>
          </div>
        </div>
      </div>
    </div>
    
    <div class="key-data-chart" v-if="keyDataChartItems.length > 1">
      <h4 class="subsection-title">📊 关键数据对比</h4>
      <div class="kd-chart-container">
        <div class="kd-chart-bars">
          <div v-for="(item, index) in keyDataChartItems" :key="index" class="kd-bar-col">
            <div class="kd-bar-value">{{ cleanValue(item.value) }}</div>
            <div class="kd-bar-wrapper">
              <div
                class="kd-bar-fill"
                :style="{
                  height: getKdBarHeight(item) + '%',
                  backgroundColor: kdColors[index % kdColors.length],
                  animationDelay: index * 0.15 + 's'
                }"
              ></div>
            </div>
            <div class="kd-bar-label" :title="item.label">{{ item.label }}</div>
          </div>
        </div>
      </div>
    </div>
    
    <div class="keywords-section" v-if="topTerms.length > 0">
      <h4 class="subsection-title">关键词云</h4>
      <div class="keywords-cloud">
        <span 
          v-for="(item, index) in topTerms" 
          :key="item.term"
          class="keyword-tag"
          :style="{ 
            fontSize: getTermFontSize(item.weight) + 'px',
            animationDelay: `${index * 0.1}s`
          }"
          :title="item.category || ''"
        >
          {{ item.term }}
        </span>
      </div>
    </div>
    <!-- 回退：jieba 关键词 -->
    <div class="keywords-section" v-else-if="keywords.length > 0">
      <h4 class="subsection-title">关键词云</h4>
      <div class="keywords-cloud">
        <span 
          v-for="(keyword, index) in keywords" 
          :key="keyword"
          class="keyword-tag"
          :style="{ 
            fontSize: `${16 - index * 0.8}px`,
            animationDelay: `${index * 0.1}s`
          }"
        >
          {{ keyword }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useDocumentStore } from '../stores/document'

const documentStore = useDocumentStore()

const statistics = computed(() => {
  const doc = documentStore.getCurrentDocument
  return doc?.statistics || {}
})

const categoryData = computed(() => {
  const dist = statistics.value.category_distribution || {}
  return Object.entries(dist).map(([name, count]) => ({ name, count }))
})

const totalKeypoints = computed(() => {
  return categoryData.value.reduce((sum, cat) => sum + cat.count, 0)
})

const keywords = computed(() => {
  return statistics.value.top_keywords || []
})

// 关键数据图表项：只展示有对比意义的重要数据
const keyDataChartItems = computed(() => {
  const doc = documentStore.getCurrentDocument
  const raw = doc?.summary?.key_data || []
  return raw.filter(item => {
    if (typeof item === 'string') return false
    // 只保留标记为对比数据的项
    if (!item.is_comparison) return false
    const n = item.numeric != null ? Number(item.numeric) : null
    if (n != null && !isNaN(n) && n >= 0) return true
    const match = String(item.value || '').match(/([\d.]+)/)
    return match && parseFloat(match[1]) >= 0
  }).slice(0, 6)  // 最多 6 个
})

const kdColors = ['#3a9fd8', '#c09060', '#ff6b6b', '#ffa94d', '#51cf66', '#339af0', '#e64980', '#20c997']

function getKdBarHeight(item) {
  let n = item.numeric != null ? Number(item.numeric) : null
  if (n == null || isNaN(n)) {
    const match = String(item.value || '').match(/([\d.]+)/)
    n = match ? parseFloat(match[1]) : 0
  }
  if (item.type === 'percentage' || (item.unit === '%' && n <= 100)) {
    return Math.min(n, 100)
  }
  const maxVal = Math.max(...keyDataChartItems.value.map(i => {
    let v = i.numeric != null ? Number(i.numeric) : null
    if (v == null || isNaN(v)) {
      const m = String(i.value || '').match(/([\d.]+)/)
      v = m ? parseFloat(m[1]) : 0
    }
    return v
  }), 1)
  return (n / maxVal) * 100
}

const getCategoryColor = (category) => {
  const colors = {
    '核心观点': '#3a9fd8',
    '关键数据': '#ff6b6b',
    '方法建议': '#ffa94d',
    '结论总结': '#51cf66',
    '重点内容': '#74c0fc'
  }
  return colors[category] || '#7f8c8d'
}

// LLM 返回的专业术语词云
const topTerms = computed(() => {
  const doc = documentStore.getCurrentDocument
  return doc?.summary?.top_terms || []
})

// 根据权重计算字体大小 (12px - 28px)
function getTermFontSize(weight) {
  const w = Number(weight) || 50
  return Math.max(12, Math.min(28, 12 + (w / 100) * 16))
}

// 修复数字中的多余空格
function cleanValue(str) {
  if (!str) return str
  let s = String(str).replace(/(\d)\s+\.\s+(\d)/g, '$1.$2')
  s = s.replace(/(\d)\s+(%)/g, '$1$2')
  s = s.replace(/(\d)\s+(\d)/g, '$1$2')
  s = s.replace(/(\d)\s+(\d)/g, '$1$2')
  return s
}
</script>

<style scoped>
.statistics-tab {
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

.statistics-header {
  margin-bottom: 24px;
}

.section-title {
  font-size: 20px;
  font-weight: 700;
  color: #3a3630;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}

.stat-card {
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  box-shadow: 0 4px 12px rgba(58, 159, 216, 0.25);
  transition: all 0.3s ease;
  animation: scaleIn 0.5s ease;
}

@keyframes scaleIn {
  from {
    opacity: 0;
    transform: scale(0.8);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.stat-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 8px 20px rgba(58, 159, 216, 0.35);
}

.stat-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 13px;
  opacity: 0.9;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
}

.category-distribution,
.keywords-section {
  margin-bottom: 32px;
}

.subsection-title {
  font-size: 16px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 16px;
}

.category-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.category-item {
  animation: slideInLeft 0.5s ease;
}

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.category-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
}

.category-name {
  color: #e2e8f0;
  font-weight: 500;
}

.category-count {
  color: #3a9fd8;
  font-weight: 700;
}

.category-bar {
  height: 8px;
  background: #e0d8cb;
  border-radius: 4px;
  overflow: hidden;
}

.category-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.8s ease;
}

.keywords-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.keyword-tag {
  display: inline-block;
  padding: 8px 16px;
  background: linear-gradient(135deg, #f5f1ea 0%, #f5f0e8 100%);
  color: #495057;
  border-radius: 20px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  animation: popIn 0.5s ease;
  border: 1px solid #d5cabb;
}

@keyframes popIn {
  0% {
    opacity: 0;
    transform: scale(0);
  }
  60% {
    transform: scale(1.1);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

.keyword-tag:hover {
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(58, 159, 216, 0.25);
}

.key-data-chart {
  margin-bottom: 32px;
}

.kd-chart-container {
  background: linear-gradient(135deg, #f5f1ea 0%, #ffffff 100%);
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #d5cabb;
}

.kd-chart-bars {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  height: 200px;
  padding: 0 8px;
}

.kd-bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  min-width: 0;
  height: 100%;
}

.kd-bar-value {
  font-size: 11px;
  font-weight: 700;
  color: #3a9fd8;
  white-space: nowrap;
  text-align: center;
}

.kd-bar-wrapper {
  flex: 1;
  width: 100%;
  max-width: 48px;
  background: rgba(58, 159, 216, 0.06);
  border-radius: 6px 6px 0 0;
  display: flex;
  align-items: flex-end;
  overflow: hidden;
}

.kd-bar-fill {
  width: 100%;
  border-radius: 6px 6px 0 0;
  min-height: 4px;
  transition: height 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  animation: barGrowUp 0.8s ease-out;
}

@keyframes barGrowUp {
  from { height: 0 !important; }
}

.kd-bar-label {
  font-size: 10px;
  color: #8a7e72;
  text-align: center;
  max-width: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
