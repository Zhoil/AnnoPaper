<template>
  <div class="keypoints-tab">
    <div class="keypoints-header">
      <h3 class="section-title">🔥 核心论点</h3>
      <div class="keypoints-stats">
        <span class="stat-badge">共 {{ keypoints.length }} 个</span>
        <span class="stat-badge">按重要性排序</span>
      </div>
    </div>
    
    <div class="keypoints-list">
      <TransitionGroup name="list">
        <div 
          v-for="(kp, index) in keypoints" 
          :key="kp.id"
          class="keypoint-card"
          :class="getCardClass(kp.importance)"
          :style="{ animationDelay: `${index * 0.08}s` }"
        >
          <!-- 卡片头部：排名 + 标签 + 分数 -->
          <div class="card-top" @click="$emit('scroll-to', kp.id)">
            <div class="card-rank" :class="getRankClass(index)">
              <span class="rank-number">{{ index + 1 }}</span>
              <span class="rank-label" v-if="index === 0">最重要</span>
              <span class="rank-label" v-else-if="index < 3">重要</span>
            </div>
            <div v-if="kp.annotation_label" class="card-label-badge">{{ kp.annotation_label }}</div>
            <div class="card-importance-badge" :style="{ backgroundColor: getImportanceColor(kp.importance) }">
              {{ kp.importance }}分
            </div>
          </div>
          
          <!-- 论点完整内容 -->
          <div class="card-content" @click="$emit('scroll-to', kp.id)">
            <div class="card-point">
              <span class="point-icon">📌</span>
              <p class="point-text">{{ kp.content }}</p>
            </div>
          </div>

          <!-- 展开/折叠论据按钮 -->
          <div 
            v-if="kp.evidence && kp.evidence.length > 0"
            class="evidence-toggle"
            @click.stop="toggleEvidence(kp.id)"
          >
            <span class="toggle-icon" :class="{ expanded: expandedIds.has(kp.id) }">▶</span>
            <span class="toggle-text">{{ expandedIds.has(kp.id) ? '收起论据' : `查看 ${kp.evidence.length} 条支撑论据` }}</span>
          </div>

          <!-- 论据列表（可展开） -->
          <Transition name="slide">
            <div v-if="expandedIds.has(kp.id) && kp.evidence" class="evidence-list">
              <div 
                v-for="(ev, evIdx) in kp.evidence" 
                :key="evIdx"
                class="evidence-item"
                @click.stop="$emit('scroll-to', kp.id + evIdx + 1)"
              >
                <div class="evidence-marker">
                  <span class="evidence-index">{{ evIdx + 1 }}</span>
                </div>
                <div class="evidence-content">
                  <p class="evidence-text">{{ ev.text }}</p>
                  <span v-if="ev.page" class="evidence-page">📄 第{{ ev.page }}页</span>
                </div>
              </div>
            </div>
          </Transition>
          
          <!-- 重要性进度条 -->
          <div class="card-footer">
            <div class="importance-bar-container">
              <div class="importance-bar-label">重要性</div>
              <div class="importance-bar">
                <div 
                  class="importance-fill" 
                  :style="{ 
                    width: `${kp.importance}%`,
                    backgroundColor: getImportanceColor(kp.importance)
                  }"
                >
                  <span class="importance-text">{{ kp.importance }}%</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive } from 'vue'
import { useDocumentStore } from '../stores/document'

const emit = defineEmits(['scroll-to'])
const documentStore = useDocumentStore()

// 展开状态管理
const expandedIds = reactive(new Set())

const toggleEvidence = (id) => {
  if (expandedIds.has(id)) {
    expandedIds.delete(id)
  } else {
    expandedIds.add(id)
  }
}

const keypoints = computed(() => {
  const doc = documentStore.getCurrentDocument
  if (!doc || !doc.keypoints) return []
  // 仅显示核心论点（论据通过展开查看）
  return doc.keypoints.filter(kp => kp.category === '核心论点')
})

const getImportanceColor = (importance) => {
  if (importance >= 80) return '#ff6b6b'
  if (importance >= 60) return '#ffa94d'
  if (importance >= 40) return '#ffd43b'
  return '#74c0fc'
}

const getCardClass = (importance) => {
  if (importance >= 90) return 'card-critical'
  if (importance >= 75) return 'card-high'
  if (importance >= 60) return 'card-medium'
  return 'card-normal'
}

const getRankClass = (index) => {
  if (index === 0) return 'rank-first'
  if (index < 3) return 'rank-top'
  return 'rank-normal'
}
</script>

<style scoped>
.keypoints-tab {
  animation: fadeIn 0.5s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.keypoints-header {
  margin-bottom: 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 2px solid #d5cabb;
}

.section-title {
  font-size: 22px;
  font-weight: 700;
  color: #3a3630;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.keypoints-stats {
  display: flex;
  gap: 12px;
}

.stat-badge {
  padding: 6px 14px;
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  box-shadow: 0 2px 8px rgba(58, 159, 216, 0.25);
}

.keypoints-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.keypoint-card {
  background: #ffffff;
  border-radius: 16px;
  padding: 20px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid #d5cabb;
  animation: slideInRight 0.5s ease;
  box-shadow: 0 2px 12px rgba(192, 144, 96, 0.06);
  position: relative;
  overflow: hidden;
}

.keypoint-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: linear-gradient(180deg, #6db8e3 0%, #3a9fd8 100%);
  transform: scaleY(0);
  transition: transform 0.3s ease;
}

.keypoint-card:hover::before {
  transform: scaleY(1);
}

.card-critical { border-left: 4px solid #ff6b6b; background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%); }
.card-high { border-left: 4px solid #ffa94d; background: linear-gradient(135deg, #fff9f0 0%, #ffffff 100%); }
.card-medium { border-left: 4px solid #ffd43b; background: linear-gradient(135deg, #fffbf0 0%, #ffffff 100%); }
.card-normal { border-left: 4px solid #74c0fc; background: linear-gradient(135deg, #f0f9ff 0%, #ffffff 100%); }

@keyframes slideInRight {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: translateX(0); }
}

.keypoint-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(192, 144, 96, 0.1);
  border-color: #3a9fd8;
}

.card-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  cursor: pointer;
}

.card-rank {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: linear-gradient(135deg, #f5f0e8 0%, #ede6da 100%);
  border-radius: 20px;
  font-weight: 700;
  color: #8a7e72;
}

.rank-first {
  background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
  color: #1a1a1a;
  box-shadow: 0 2px 12px rgba(255, 215, 0, 0.4);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}

.rank-top {
  background: linear-gradient(135deg, #ffa94d 0%, #ff8787 100%);
  color: white;
}

.rank-number { font-size: 18px; font-weight: 800; }
.rank-label { font-size: 11px; letter-spacing: 1px; text-transform: uppercase; font-weight: 600; }

.card-label-badge {
  padding: 4px 10px;
  background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
  color: #2e7d32;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.card-importance-badge {
  margin-left: auto;
  padding: 6px 14px;
  border-radius: 20px;
  color: white;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.5px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.card-content {
  margin-bottom: 12px;
  cursor: pointer;
}

.card-point {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.point-icon {
  font-size: 18px;
  flex-shrink: 0;
  margin-top: 2px;
}

.point-text {
  font-size: 15px;
  line-height: 1.8;
  color: #3a3630;
  margin: 0;
  font-weight: 500;
  word-break: break-word;
}

/* ── 论据展开/折叠 ── */
.evidence-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin: 8px 0;
  background: rgba(58, 159, 216, 0.04);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}

.evidence-toggle:hover {
  background: rgba(58, 159, 216, 0.08);
}

.toggle-icon {
  font-size: 12px;
  color: #3a9fd8;
  transition: transform 0.3s ease;
  display: inline-block;
}

.toggle-icon.expanded {
  transform: rotate(90deg);
}

.toggle-text {
  font-size: 13px;
  color: #3a9fd8;
  font-weight: 600;
}

.evidence-list {
  margin: 8px 0 12px;
  padding-left: 8px;
  border-left: 3px solid #51cf66;
}

.evidence-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  margin: 6px 0;
  background: linear-gradient(135deg, #f0fff4 0%, #ffffff 100%);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.evidence-item:hover {
  background: linear-gradient(135deg, #e6ffe8 0%, #f0fff4 100%);
  transform: translateX(4px);
}

.evidence-marker {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, #51cf66 0%, #40c057 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.evidence-index {
  color: white;
  font-size: 12px;
  font-weight: 700;
}

.evidence-content {
  flex: 1;
  min-width: 0;
}

.evidence-text {
  font-size: 14px;
  line-height: 1.7;
  color: #495057;
  margin: 0;
  word-break: break-word;
}

.evidence-page {
  display: inline-block;
  margin-top: 4px;
  font-size: 11px;
  color: #868e96;
  background: #f1f3f5;
  padding: 2px 8px;
  border-radius: 8px;
}

/* ── 展开动画 ── */
.slide-enter-active {
  transition: all 0.3s ease;
  max-height: 2000px;
}
.slide-leave-active {
  transition: all 0.2s ease;
}
.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
  overflow: hidden;
}

/* ── 底部进度条 ── */
.card-footer {
  display: flex;
  align-items: center;
  gap: 12px;
}

.importance-bar-container {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.importance-bar-label {
  font-size: 12px;
  color: #8a7e72;
  font-weight: 600;
  min-width: 50px;
}

.importance-bar {
  flex: 1;
  height: 12px;
  background: rgba(58, 159, 216, 0.06);
  border-radius: 20px;
  overflow: hidden;
  box-shadow: inset 0 2px 4px rgba(192, 144, 96, 0.08);
}

.importance-fill {
  height: 100%;
  background: linear-gradient(90deg, #6db8e3 0%, #3a9fd8 100%);
  border-radius: 20px;
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding-right: 8px;
}

.importance-text {
  font-size: 10px;
  font-weight: 700;
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  letter-spacing: 0.5px;
}

.list-move,
.list-enter-active,
.list-leave-active {
  transition: all 0.5s ease;
}
.list-enter-from { opacity: 0; transform: translateX(30px); }
.list-leave-to { opacity: 0; transform: translateX(-30px); }
</style>
