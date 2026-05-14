<template>
  <div class="keypoints-tab">
    <div class="keypoints-header">
      <h3 class="section-title">🔥 核心论点</h3>
      <div class="keypoints-stats">
        <span class="stat-badge">共 {{ keypoints.length }} 个</span>
        <span class="stat-badge">按重要性排序</span>
        <button
          class="logic-toggle-btn"
          :class="{ active: showLogic }"
          :disabled="!recordId"
          @click="toggleLogicView"
        >
          <span v-if="showLogic">📋 列表视图</span>
          <span v-else>🔗 论证链路</span>
        </button>
      </div>
    </div>

    <!-- 论证链路面板（SVG 关系图：根 → 论点 → 论据连线） -->
    <div v-if="showLogic" class="logic-panel">
      <div class="logic-toolbar">
        <div class="logic-stats" v-if="logicTree && logicTree.stats">
          论点 {{ logicTree.stats.points }} 个 · 论据 {{ logicTree.stats.evidences }} 条
        </div>
        <div class="logic-hint">💡 悬停节点高亮关联链路 · 点击跳转原文</div>
        <button class="logic-btn" :disabled="logicLoading" @click="refreshLogic">
          <span v-if="logicLoading">生成中…</span>
          <span v-else>🔄 重生成</span>
        </button>
        <button class="logic-btn primary" :disabled="!treePoints.length" @click="openFullscreen">
          🔍 全屏查看
        </button>
      </div>
      <div v-if="logicLoading" class="logic-empty">正在构建论证链路…</div>
      <div v-else-if="!treePoints.length" class="logic-empty">未生成论证链路，点击上方“重生成”</div>
      <div v-else class="logic-graph" ref="graphWrap">
        <svg class="logic-graph-svg" :width="svgW" :height="svgH">
          <path
            v-for="(link, idx) in links"
            :key="'l-' + idx"
            :d="link.d"
            :stroke="link.color"
            :stroke-width="link.kind === 'root' ? 2.4 : 1.6"
            class="logic-link"
            :class="{ 'link-active': hoverPointId === link.pointId, 'link-dim': hoverPointId && hoverPointId !== link.pointId }"
            fill="none"
          />
        </svg>
        <div class="logic-graph-grid">
          <div class="col col-root">
            <div class="node node-root">
              <span class="node-root-icon">📄</span>
              <span class="node-root-text">{{ logicTree?.tree?.root || '文档' }}</span>
            </div>
          </div>
          <div class="col col-points">
            <div
              v-for="(p, i) in treePoints"
              :key="'p-' + (p.id || i)"
              class="node node-point"
              :class="[getImportanceClass(p.importance), { 'node-active': hoverPointId === p.id, 'node-dim': hoverPointId && hoverPointId !== p.id }]"
              :data-pid="String(p.id)"
              :data-importance="p.importance || 0"
              @mouseenter="hoverPointId = p.id"
              @mouseleave="hoverPointId = null"
              @click="$emit('scroll-to', p.id)"
            >
              <div class="node-head">
                <span class="node-badge">#{{ i + 1 }}</span>
                <span v-if="p.label" class="node-label">{{ p.label }}</span>
                <span class="node-score" :style="{ backgroundColor: getImportanceColor(p.importance) }">
                  {{ p.importance || 0 }}
                </span>
              </div>
              <div class="node-text">{{ p.text }}</div>
              <div class="node-meta">
                <span v-if="p.page">📍 第 {{ p.page }} 页</span>
                <span>🔹 {{ (p.evidences || []).length }} 条论据</span>
              </div>
            </div>
          </div>
          <div class="col col-evidences">
            <template v-for="(p, i) in treePoints" :key="'eg-' + (p.id || i)">
              <div
                v-for="(ev, j) in (p.evidences || [])"
                :key="'ev-' + (p.id || i) + '-' + j"
                class="node node-evidence"
                :class="{ 'node-active': hoverPointId === p.id, 'node-dim': hoverPointId && hoverPointId !== p.id }"
                :data-pid="String(p.id)"
                @mouseenter="hoverPointId = p.id"
                @mouseleave="hoverPointId = null"
                @click="$emit('scroll-to', ev.id || p.id)"
              >
                <span class="ev-arrow">↳</span>
                <span class="ev-text">{{ ev.text }}</span>
                <span v-if="ev.page" class="ev-page">p.{{ ev.page }}</span>
              </div>
            </template>
         </div>
        </div>
      </div>
    </div>

    <!-- 论证逻辑图（与上方 SVG 三层树并列，模型直接给出，支持拖拽调整） -->
    <div v-if="showLogic" class="logic-panel logic-panel-extra">
      <div class="logic-toolbar">
        <div class="logic-title-inline">
          <span class="logic-title-icon">🧩</span>
          <span class="logic-title-text">论证逻辑图</span>
          <span class="logic-title-sub">由模型提炼 · 可拖拽调整布局</span>
        </div>
        <div class="logic-hint">💡 拖动节点 / 滚轮缩放 / 右下角可 fit-view</div>
      </div>
      <ArgumentLogicGraph :graph="argumentLogicGraph" />
    </div>

    <div v-show="!showLogic" class="keypoints-list">
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

    <!-- 全屏 Modal（SVG 关系图） -->
    <Teleport to="body">
      <Transition name="modal-fade">
        <div v-if="fullscreen" class="logic-modal" @click.self="closeFullscreen">
          <div class="logic-modal-content">
            <div class="logic-modal-header">
              <span class="logic-modal-title">🔗 论证链路 · 全屏查看</span>
              <div class="logic-modal-actions">
                <span v-if="logicTree && logicTree.stats" class="logic-stats">
                  论点 {{ logicTree.stats.points }} · 论据 {{ logicTree.stats.evidences }}
                </span>
                <span class="logic-hint">💡 悬停高亮 · 点击跳转</span>
                <button class="logic-btn close" @click="closeFullscreen">✕ 关闭</button>
              </div>
            </div>
            <div class="logic-modal-body">
              <div class="logic-graph logic-graph-full" ref="fullGraphWrap">
                <svg class="logic-graph-svg" :width="fullSvgW" :height="fullSvgH">
                  <path
                    v-for="(link, idx) in fullLinks"
                    :key="'fl-' + idx"
                    :d="link.d"
                    :stroke="link.color"
                    :stroke-width="link.kind === 'root' ? 2.8 : 1.8"
                    class="logic-link"
                    :class="{ 'link-active': fullHoverPointId === link.pointId, 'link-dim': fullHoverPointId && fullHoverPointId !== link.pointId }"
                    fill="none"
                  />
                </svg>
                <div class="logic-graph-grid logic-graph-grid-full">
                  <div class="col col-root">
                    <div class="node node-root node-root-full">
                      <span class="node-root-icon">📄</span>
                      <span class="node-root-text">{{ logicTree?.tree?.root || '文档' }}</span>
                    </div>
                  </div>
                  <div class="col col-points">
                    <div
                      v-for="(p, i) in treePoints"
                      :key="'fp-' + (p.id || i)"
                      class="node node-point"
                      :class="[getImportanceClass(p.importance), { 'node-active': fullHoverPointId === p.id, 'node-dim': fullHoverPointId && fullHoverPointId !== p.id }]"
                      :data-pid="String(p.id)"
                      :data-importance="p.importance || 0"
                      @mouseenter="fullHoverPointId = p.id"
                      @mouseleave="fullHoverPointId = null"
                    >
                      <div class="node-head">
                        <span class="node-badge">#{{ i + 1 }}</span>
                        <span v-if="p.label" class="node-label">{{ p.label }}</span>
                        <span class="node-score" :style="{ backgroundColor: getImportanceColor(p.importance) }">
                          {{ p.importance || 0 }}
                        </span>
                      </div>
                      <div class="node-text">{{ p.text }}</div>
                      <div class="node-meta">
                        <span v-if="p.page">📍 第 {{ p.page }} 页</span>
                        <span>🔹 {{ (p.evidences || []).length }} 条论据</span>
                      </div>
                    </div>
                  </div>
                  <div class="col col-evidences">
                    <template v-for="(p, i) in treePoints" :key="'feg-' + (p.id || i)">
                      <div
                        v-for="(ev, j) in (p.evidences || [])"
                        :key="'fev-' + (p.id || i) + '-' + j"
                        class="node node-evidence"
                        :class="{ 'node-active': fullHoverPointId === p.id, 'node-dim': fullHoverPointId && fullHoverPointId !== p.id }"
                        :data-pid="String(p.id)"
                        @mouseenter="fullHoverPointId = p.id"
                        @mouseleave="fullHoverPointId = null"
                      >
                        <span class="ev-arrow">↳</span>
                        <span class="ev-text">{{ ev.text }}</span>
                        <span v-if="ev.page" class="ev-page">p.{{ ev.page }}</span>
                      </div>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useDocumentStore } from '../stores/document'
import ArgumentLogicGraph from './ArgumentLogicGraph.vue'

const emit = defineEmits(['scroll-to'])
const documentStore = useDocumentStore()
const { logicTree, logicLoading } = storeToRefs(documentStore)

// 展开状态管理
const expandedIds = reactive(new Set())

// 论证链路状态
const showLogic = ref(false)
const fullscreen = ref(false)

// ── SVG 关系图相关 ref ──
const graphWrap = ref(null)
const fullGraphWrap = ref(null)
const svgW = ref(0)
const svgH = ref(0)
const fullSvgW = ref(0)
const fullSvgH = ref(0)
const links = ref([])
const fullLinks = ref([])
const hoverPointId = ref(null)
const fullHoverPointId = ref(null)
let ro = null
let roFull = null
let rafId = null
let rafIdFull = null

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
  return doc.keypoints.filter(kp => kp.category === '核心论点')
})

const recordId = computed(() => {
  const doc = documentStore.getCurrentDocument
  return doc?.record_id || doc?.id || null
})

// 模型给出的论证逻辑图（结构独立于 SVG 三层树）
const argumentLogicGraph = computed(() => {
  const doc = documentStore.getCurrentDocument
  const g = doc?.argument_logic_graph
  if (g && Array.isArray(g.nodes) && Array.isArray(g.edges)) return g
  return { nodes: [], edges: [] }
})

// 论证链路数据：优先使用 logicTree.tree.points，回退到 keypoints 合成
const treePoints = computed(() => {
  const pts = logicTree.value?.tree?.points
  if (Array.isArray(pts) && pts.length) return pts
  // fallback：从Keypoints构造
  return keypoints.value.map((kp, idx) => ({
    id: kp.id,
    text: kp.content,
    label: kp.annotation_label,
    importance: kp.importance,
    page: kp.page,
    evidences: (kp.evidence || []).map((ev, j) => ({
      id: kp.id + j + 1,
      text: ev.text,
      page: ev.page
    }))
  }))
})

const getImportanceColor = (importance) => {
  if (importance >= 80) return '#ff6b6b'
  if (importance >= 60) return '#ffa94d'
  if (importance >= 40) return '#ffd43b'
  return '#74c0fc'
}

const getImportanceClass = (importance) => {
  if (importance >= 90) return 'importance-critical'
  if (importance >= 75) return 'importance-high'
  if (importance >= 60) return 'importance-medium'
  return 'importance-normal'
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

// ── 论证链路加载 ──
async function loadLogic() {
  if (!recordId.value) return
  await documentStore.fetchLogicTree(recordId.value)
}

async function refreshLogic() { await loadLogic() }

async function toggleLogicView() {
  showLogic.value = !showLogic.value
  if (showLogic.value && !logicTree.value) {
    await loadLogic()
  }
}

function openFullscreen() {
  if (!logicTree.value && !treePoints.value.length) return
  fullscreen.value = true
}

function closeFullscreen() { fullscreen.value = false }

// 切换文档时重置论证链路
watch(recordId, () => {
  showLogic.value = false
  fullscreen.value = false
  documentStore.clearAuxiliary && documentStore.clearAuxiliary()
})

// ── SVG 连线计算 ──
function makePath(a, b) {
  const dx = Math.max(40, (b.x - a.x) / 2)
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
}

function cssEscape(s) {
  if (typeof window !== 'undefined' && window.CSS && typeof window.CSS.escape === 'function') {
    return window.CSS.escape(s)
  }
  return String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => '\\' + c)
}

function computeLinksFor(container, linksRef, svgWRef, svgHRef) {
  if (!container) return
  const cRect = container.getBoundingClientRect()
  const scrollLeft = container.scrollLeft || 0
  const scrollTop = container.scrollTop || 0
  svgWRef.value = container.scrollWidth || cRect.width
  svgHRef.value = container.scrollHeight || cRect.height
  const rootEl = container.querySelector('.col-root .node-root')
  if (!rootEl) { linksRef.value = []; return }
  const anchor = (el, side) => {
    const r = el.getBoundingClientRect()
    const x = (side === 'right' ? r.right : r.left) - cRect.left + scrollLeft
    const y = r.top + r.height / 2 - cRect.top + scrollTop
    return { x, y }
  }
  const rootA = anchor(rootEl, 'right')
  const newLinks = []
  const pointNodes = container.querySelectorAll('.col-points .node-point')
  pointNodes.forEach((pNode) => {
    const pid = pNode.getAttribute('data-pid')
    const importance = Number(pNode.getAttribute('data-importance') || 0)
    const color = getImportanceColor(importance)
    const leftA = anchor(pNode, 'left')
    const rightA = anchor(pNode, 'right')
    newLinks.push({ d: makePath(rootA, leftA), color, pointId: pid, kind: 'root' })
    const sel = `.col-evidences .node-evidence[data-pid="${cssEscape(pid)}"]`
    container.querySelectorAll(sel).forEach((evEl) => {
      const evA = anchor(evEl, 'left')
      newLinks.push({ d: makePath(rightA, evA), color, pointId: pid, kind: 'ev' })
    })
  })
  linksRef.value = newLinks
}

function scheduleCompute() {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(() => {
    rafId = null
    computeLinksFor(graphWrap.value, links, svgW, svgH)
  })
}

function scheduleComputeFull() {
  if (rafIdFull) cancelAnimationFrame(rafIdFull)
  rafIdFull = requestAnimationFrame(() => {
    rafIdFull = null
    computeLinksFor(fullGraphWrap.value, fullLinks, fullSvgW, fullSvgH)
  })
}

function onWindowResize() {
  scheduleCompute()
  if (fullscreen.value) scheduleComputeFull()
}

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(() => scheduleCompute())
    roFull = new ResizeObserver(() => scheduleComputeFull())
  }
  window.addEventListener('resize', onWindowResize)
})

onBeforeUnmount(() => {
  if (ro) { try { ro.disconnect() } catch (e) {} ro = null }
  if (roFull) { try { roFull.disconnect() } catch (e) {} roFull = null }
  window.removeEventListener('resize', onWindowResize)
  if (rafId) cancelAnimationFrame(rafId)
  if (rafIdFull) cancelAnimationFrame(rafIdFull)
})

// 观察内嵌图：showLogic 打开或数据变化时重算
watch([showLogic, treePoints], async () => {
  if (!showLogic.value) return
  await nextTick()
  if (ro && graphWrap.value) {
    try { ro.disconnect() } catch (e) {}
    ro.observe(graphWrap.value)
  }
  scheduleCompute()
})

// 观察全屏图：fullscreen 打开或数据变化时重算
watch([fullscreen, treePoints], async () => {
  if (!fullscreen.value) return
  await nextTick()
  if (roFull && fullGraphWrap.value) {
    try { roFull.disconnect() } catch (e) {}
    roFull.observe(fullGraphWrap.value)
  }
  scheduleComputeFull()
})
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

/* ── 论证链路切换按钮 ── */
.logic-toggle-btn {
  padding: 6px 14px;
  background: linear-gradient(135deg, #b07f5b 0%, #8b6240 100%);
  color: white;
  border: none;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(176, 127, 91, 0.3);
  transition: all 0.2s ease;
}

.logic-toggle-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(176, 127, 91, 0.4);
}

.logic-toggle-btn.active {
  background: linear-gradient(135deg, #3a9fd8 0%, #1c7fb8 100%);
  box-shadow: 0 2px 8px rgba(58, 159, 216, 0.4);
}

.logic-toggle-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ── 论证链路面板 ── */
.logic-panel {
  margin-bottom: 24px;
  padding: 20px;
  background: linear-gradient(135deg, #fbf6ee 0%, #ffffff 100%);
  border-radius: 14px;
  border: 1px solid #e8dcc8;
  box-shadow: 0 4px 16px rgba(192, 144, 96, 0.08);
  animation: fadeIn 0.4s ease;
}

/* 论证逻辑图（下方并列面板）专属样式 */
.logic-panel-extra {
  background: linear-gradient(135deg, #fffdf9 0%, #fbf6ee 100%);
  margin-bottom: 24px;
}
.logic-title-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
.logic-title-icon {
  font-size: 18px;
}
.logic-title-text {
  font-size: 15px;
  font-weight: 700;
  color: #5c4a38;
  letter-spacing: 0.3px;
}
.logic-title-sub {
  font-size: 12px;
  color: #8a7e72;
  padding-left: 4px;
  border-left: 1px solid #e8dcc8;
  margin-left: 4px;
}

.logic-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed #e8dcc8;
}

.logic-stats {
  font-size: 13px;
  color: #8a7e72;
  font-weight: 600;
  margin-right: auto;
}

.logic-hint {
  font-size: 11px;
  color: #8a7e72;
  padding: 4px 10px;
  background: rgba(176, 127, 91, 0.08);
  border-radius: 10px;
  letter-spacing: 0.3px;
  margin-right: 4px;
  white-space: nowrap;
}

.logic-btn {
  padding: 6px 14px;
  background: #ffffff;
  color: #b07f5b;
  border: 1px solid #e8dcc8;
  border-radius: 18px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.logic-btn:hover:not(:disabled) {
  background: #fbf6ee;
  border-color: #b07f5b;
}

.logic-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.logic-btn.primary {
  background: linear-gradient(135deg, #3a9fd8 0%, #1c7fb8 100%);
  color: white;
  border-color: transparent;
  box-shadow: 0 2px 8px rgba(58, 159, 216, 0.3);
}

.logic-btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(58, 159, 216, 0.45);
}

.logic-btn.close {
  background: #ff6b6b;
  color: white;
  border-color: transparent;
}

/* ── 论证链路：SVG 关系图容器 ── */
.logic-graph {
  position: relative;
  width: 100%;
  padding: 16px 8px;
  min-height: 320px;
  overflow: auto;
  max-height: 680px;
  border-radius: 10px;
}

.logic-graph::-webkit-scrollbar { width: 8px; height: 8px; }
.logic-graph::-webkit-scrollbar-track { background: #f5f1ea; border-radius: 4px; }
.logic-graph::-webkit-scrollbar-thumb { background: linear-gradient(180deg, #b07f5b, #8b6240); border-radius: 4px; }

.logic-graph-full {
  max-height: none;
  min-height: 100%;
  padding: 24px 16px;
}

.logic-graph-svg {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 0;
  overflow: visible;
}

.logic-graph-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(160px, 0.9fr) minmax(240px, 1.6fr) minmax(220px, 1.6fr);
  gap: 28px 56px;
  align-items: start;
  min-width: 720px;
}

.logic-graph-grid-full {
  grid-template-columns: minmax(200px, 1fr) minmax(320px, 2fr) minmax(300px, 2fr);
  gap: 36px 80px;
  min-width: 960px;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.col-root {
  position: sticky;
  top: 8px;
  align-self: start;
  justify-content: center;
  min-height: 120px;
}

.node {
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
  word-break: break-word;
}

.node-root {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 16px 22px;
  background: linear-gradient(135deg, #3a9fd8 0%, #1c7fb8 100%);
  color: #ffffff;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 700;
  box-shadow: 0 6px 20px rgba(58, 159, 216, 0.3);
  max-width: 100%;
}

.node-root-full {
  padding: 20px 28px;
  font-size: 18px;
}

.node-root-icon { font-size: 20px; }
.node-root-text { line-height: 1.4; }

.node-point {
  padding: 14px 16px;
  background: #ffffff;
  border: 1px solid #e8dcc8;
  border-left: 4px solid #74c0fc;
  border-radius: 12px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: 0 2px 10px rgba(192, 144, 96, 0.08);
}

.node-point:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(58, 159, 216, 0.16);
}

.node-point.importance-critical { border-left-color: #ff6b6b; background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%); }
.node-point.importance-high     { border-left-color: #ffa94d; background: linear-gradient(135deg, #fff9f0 0%, #ffffff 100%); }
.node-point.importance-medium   { border-left-color: #ffd43b; background: linear-gradient(135deg, #fffbf0 0%, #ffffff 100%); }
.node-point.importance-normal   { border-left-color: #74c0fc; background: linear-gradient(135deg, #f0f9ff 0%, #ffffff 100%); }

.node-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.node-badge {
  font-size: 12px;
  font-weight: 800;
  color: #b07f5b;
  background: rgba(176, 127, 91, 0.12);
  padding: 3px 8px;
  border-radius: 8px;
  letter-spacing: 0.3px;
}

.node-label {
  padding: 3px 10px;
  background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
  color: #2e7d32;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
}

.node-score {
  margin-left: auto;
  padding: 3px 10px;
  border-radius: 12px;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.node-text {
  font-size: 14px;
  line-height: 1.7;
  color: #3a3630;
  font-weight: 500;
}

.node-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 11px;
  color: #8a7e72;
}

.node-meta span {
  padding: 2px 8px;
  background: #f5f1ea;
  border-radius: 8px;
  font-weight: 600;
}

.node-evidence {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #f0fff4 0%, #ffffff 100%);
  border: 1px solid #d4f1db;
  border-left: 3px solid #51cf66;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  color: #3a3630;
  cursor: pointer;
  box-shadow: 0 1px 6px rgba(81, 207, 102, 0.08);
}

.node-evidence:hover {
  transform: translateX(2px);
  background: linear-gradient(135deg, #e6ffe8 0%, #f0fff4 100%);
}

.ev-arrow {
  color: #51cf66;
  font-weight: 700;
  flex-shrink: 0;
}

.ev-text {
  flex: 1;
  word-break: break-word;
}

.ev-page {
  flex-shrink: 0;
  font-size: 11px;
  color: #868e96;
  background: #f1f3f5;
  padding: 2px 8px;
  border-radius: 8px;
  align-self: flex-start;
}

/* 悬停联动样式 */
.node-active {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(58, 159, 216, 0.28);
  opacity: 1 !important;
}

.node-dim {
  opacity: 0.32;
}

.logic-link {
  fill: none;
  transition: opacity 0.2s ease, stroke-width 0.2s ease;
  opacity: 0.62;
}

.link-active {
  opacity: 1;
  stroke-width: 3 !important;
  filter: drop-shadow(0 2px 6px rgba(58, 159, 216, 0.35));
}

.link-dim {
  opacity: 0.12;
}

.logic-empty {
  text-align: center;
  color: #8a7e72;
  font-style: italic;
  padding: 60px 20px;
}

/* ── 全屏 Modal ── */
.logic-modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.logic-modal-content {
  width: min(96vw, 1400px);
  height: min(92vh, 900px);
  background: #ffffff;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 48px rgba(0, 0, 0, 0.3);
}

.logic-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  background: linear-gradient(135deg, #fbf6ee 0%, #ffffff 100%);
}

.logic-modal-body::-webkit-scrollbar { width: 10px; }
.logic-modal-body::-webkit-scrollbar-track { background: #f5f1ea; }
.logic-modal-body::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #b07f5b, #8b6240);
  border-radius: 5px;
}

.logic-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: linear-gradient(135deg, #fbf6ee 0%, #f5f1ea 100%);
  border-bottom: 1px solid #e8dcc8;
  flex-shrink: 0;
}

.logic-modal-title {
  font-size: 16px;
  font-weight: 700;
  color: #3a3630;
}

.logic-modal-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.logic-modal-actions .logic-stats {
  font-size: 13px;
  color: #8a7e72;
  font-weight: 600;
  margin-right: 8px;
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.2s ease;
}
.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}
</style>
