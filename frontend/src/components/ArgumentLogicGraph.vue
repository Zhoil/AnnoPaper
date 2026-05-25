<template>
  <div class="arg-logic-wrap">
    <div v-if="!hasGraph" class="arg-empty">
      <span class="arg-empty-icon">🧠</span>
      <span class="arg-empty-text">LLM 未输出逻辑推理图</span>
      <span class="arg-empty-hint">可能因文档过短或结构不清晰</span>
    </div>
    <div v-else class="arg-canvas" :class="{ 'arg-canvas-full': expanded }">
      <div class="arg-legend">
        <div class="legend-group">
          <span class="legend-title">节点：</span>
          <span class="legend-item premise">● 前提</span>
          <span class="legend-item intermediate">● 中间</span>
          <span class="legend-item conclusion">● 结论</span>
          <span class="legend-item counter">● 反例</span>
          <span class="legend-item assumption">● 假设</span>
        </div>
        <div class="legend-group">
          <span class="legend-title">边：</span>
          <span class="legend-item rel-support">— 支持</span>
          <span class="legend-item rel-rebut">┄ 反驳</span>
          <span class="legend-item rel-cause">→ 因果</span>
          <span class="legend-item rel-parallel">‖ 并列</span>
          <span class="legend-item rel-progression">⇒ 递进</span>
        </div>
        <button class="arg-btn" @click="relayout">🔁 重置布局</button>
        <button class="arg-btn primary" @click="toggleExpand">
          <span v-if="expanded">✖ 关闭全屏</span>
          <span v-else>🔍 放大查看</span>
        </button>
      </div>
      <VueFlow
        v-model:nodes="flowNodes"
        v-model:edges="flowEdges"
        :default-viewport="{ zoom: 0.85 }"
        :min-zoom="0.2"
        :max-zoom="4.0"
        :nodes-draggable="true"
        :nodes-connectable="false"
        :elements-selectable="true"
        class="arg-flow"
        fit-view-on-init
      >
        <Background :gap="16" :size="1" pattern-color="#e8dcc8" />
        <Controls position="bottom-right" :show-interactive="false" />
        <MiniMap pannable zoomable node-stroke-color="#b07f5b" node-color="#fbf6ee" mask-color="rgba(192,144,96,0.15)" />
      </VueFlow>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = defineProps({
  graph: {
    type: Object,
    default: () => ({ nodes: [], edges: [] })
  }
})

// 全屏放大状态
const expanded = ref(false)
function toggleExpand() {
  expanded.value = !expanded.value
  // 全屏切换后重建布局以适配新画布尺寸
  setTimeout(() => rebuild(), 60)
}
// ESC 快捷键关闭全屏
function onEscKey(e) {
  if (e.key === 'Escape' && expanded.value) {
    expanded.value = false
    setTimeout(() => rebuild(), 60)
  }
}
onMounted(() => {
  rebuild()
  document.addEventListener('keydown', onEscKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onEscKey)
})

const hasGraph = computed(() => {
  return props.graph && Array.isArray(props.graph.nodes) && props.graph.nodes.length > 0
})

// ---------- 节点/边颜色与样式映射 ----------
const NODE_COLORS = {
  premise:      { bg: '#e7f1ff', border: '#4dabf7', shadow: 'rgba(77,171,247,0.22)', text: '#1864ab' },
  intermediate: { bg: '#efeaff', border: '#a78bfa', shadow: 'rgba(167,139,250,0.22)', text: '#5f3dc4' },
  conclusion:   { bg: '#ffe8e8', border: '#ff6b6b', shadow: 'rgba(255,107,107,0.28)', text: '#c92a2a' },
  counter:      { bg: '#fff2e2', border: '#ff922b', shadow: 'rgba(255,146,43,0.22)', text: '#c2410c' },
  assumption:   { bg: '#f1f3f5', border: '#868e96', shadow: 'rgba(134,142,150,0.22)', text: '#495057' },
}
const TYPE_LABEL = {
  premise: '前提',
  intermediate: '中间',
  conclusion: '结论',
  counter: '反例',
  assumption: '假设',
}
const RELATION_STYLE = {
  support:     { stroke: '#4dabf7', dash: '',       width: 2,   arrow: 'arrowclosed', label: '支持' },
  rebut:       { stroke: '#ff6b6b', dash: '6,4',    width: 2,   arrow: 'arrowclosed', label: '反驳' },
  cause:       { stroke: '#51cf66', dash: '',       width: 2.4, arrow: 'arrowclosed', label: '因果' },
  parallel:    { stroke: '#868e96', dash: '2,3',    width: 1.6, arrow: '',            label: '并列' },
  progression: { stroke: '#a78bfa', dash: '',       width: 2.8, arrow: 'arrowclosed', label: '递进' },
}

// ---------- 自动分层布局（支持多层 intermediate 拆分） ----------
// 主线：premise → intermediate(1) → intermediate(2) → conclusion
// 辅线：counter / assumption 偏置
function layoutNodes(rawNodes) {
  const ROW_H = 100   // 缩小行高以容纳更多节点
  const COL_GAP = 280 // 列间距

  const groups = { premise: [], intermediate: [], conclusion: [], counter: [], assumption: [] }
  rawNodes.forEach(n => {
    const t = groups[n.type] ? n.type : 'intermediate'
    groups[t].push(n)
  })

  // 当 intermediate 超过 4 个时，拆分为两列，展现多层推理深度
  const midNodes = groups.intermediate
  const midCol1 = midNodes.slice(0, Math.ceil(midNodes.length / 2))
  const midCol2 = midNodes.slice(Math.ceil(midNodes.length / 2))
  const hasDoubleIntermediate = midCol2.length > 0

  // 计算各列 X 坐标
  const baseX = 40
  const colPremise = baseX
  const colMid1 = baseX + COL_GAP
  const colMid2 = hasDoubleIntermediate ? baseX + COL_GAP * 2 : colMid1
  const colConclusion = hasDoubleIntermediate ? baseX + COL_GAP * 3 : baseX + COL_GAP * 2

  const positioned = []
  const putColumn = (list, x, centerY) => {
    const total = list.length
    list.forEach((n, i) => {
      const y = centerY + i * ROW_H - ((total - 1) * ROW_H) / 2
      positioned.push({ raw: n, x, y })
    })
  }

  // 主布局基准 Y
  const allMainCount = groups.premise.length + midNodes.length + groups.conclusion.length
  const mainCenterY = Math.max(200, allMainCount * 28)

  putColumn(groups.premise, colPremise, mainCenterY)
  putColumn(midCol1, colMid1, mainCenterY)
  if (hasDoubleIntermediate) {
    putColumn(midCol2, colMid2, mainCenterY)
  }
  putColumn(groups.conclusion, colConclusion, mainCenterY)

  // counter：放在中间列上方
  const counterX = colMid1 + (hasDoubleIntermediate ? COL_GAP / 2 : 0)
  const counterY = mainCenterY - (Math.max(midCol1.length, groups.premise.length) + 1) * ROW_H / 2 - 60
  putColumn(groups.counter, counterX, counterY)

  // assumption：放在前提列下方
  const assumpY = mainCenterY + (groups.premise.length + 1) * ROW_H / 2 + 60
  putColumn(groups.assumption, colPremise + COL_GAP / 2, assumpY)

  return positioned
}

function buildFlow(graph) {
  const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : []
  const rawEdges = Array.isArray(graph?.edges) ? graph.edges : []

  const positioned = layoutNodes(rawNodes)
  const nodes = positioned.map(({ raw, x, y }) => {
    const color = NODE_COLORS[raw.type] || NODE_COLORS.intermediate
    const typeLabel = TYPE_LABEL[raw.type] || '节点'
    // 节点显示：类型标签 + 标题 + summary 简述
    const summaryText = raw.summary ? `\n${raw.summary}` : ''
    return {
      id: raw.id,
      type: 'default',
      position: { x, y },
      data: { raw },
      label: `【${typeLabel}】${raw.label}${summaryText}`,
      style: {
        background: color.bg,
        color: color.text,
        border: `2px solid ${color.border}`,
        borderRadius: '12px',
        padding: '10px 14px',
        width: '240px',
        fontSize: '12px',
        lineHeight: '1.5',
        fontWeight: 600,
        boxShadow: `0 4px 14px ${color.shadow}`,
        whiteSpace: 'pre-line',
        textAlign: 'left',
      },
      title: raw.summary || '',
    }
  })

  const edges = rawEdges.map((e, idx) => {
    const rs = RELATION_STYLE[e.relation] || RELATION_STYLE.support
    return {
      id: `e-${idx}-${e.from}-${e.to}`,
      source: e.from,
      target: e.to,
      type: 'smoothstep',
      animated: e.relation === 'progression',
      label: e.note ? `${rs.label}·${e.note}` : rs.label,
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 4,
      labelBgStyle: { fill: '#ffffff', fillOpacity: 0.92, stroke: '#e8dcc8' },
      labelStyle: { fill: '#5c4a38', fontSize: '11px', fontWeight: 600 },
      markerEnd: rs.arrow ? { type: rs.arrow, color: rs.stroke } : undefined,
      style: {
        stroke: rs.stroke,
        strokeWidth: rs.width,
        strokeDasharray: rs.dash || undefined,
      },
    }
  })

  return { nodes, edges }
}

const flowNodes = ref([])
const flowEdges = ref([])

function rebuild() {
  const { nodes, edges } = buildFlow(props.graph)
  flowNodes.value = nodes
  flowEdges.value = edges
}

function relayout() {
  rebuild()
}

// 仅监听 props.graph 引用变化 + 节点/边数量变化
watch(
  () => [props.graph, props.graph?.nodes?.length || 0, props.graph?.edges?.length || 0],
  () => { rebuild() }
)
</script>

<style scoped>
.arg-logic-wrap {
  width: 100%;
  position: relative;
}

.arg-empty {
  height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #8a7e72;
  background: rgba(251, 246, 238, 0.6);
  border: 1px dashed #e8dcc8;
  border-radius: 10px;
}
.arg-empty-icon { font-size: 32px; }
.arg-empty-text { font-size: 14px; color: #5c4a38; font-weight: 600; }
.arg-empty-hint { font-size: 12px; color: #a39383; }

.arg-canvas {
  position: relative;
  width: 100%;
  height: 480px;
  border: 1px solid #e8dcc8;
  border-radius: 10px;
  background: linear-gradient(180deg, #fffdf9 0%, #f8f1e5 100%);
  overflow: hidden;
  transition: all 0.25s ease;
}
/* 全屏放大模式 */
.arg-canvas-full {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100vw;
  height: 100vh;
  border-radius: 0;
  z-index: 9999;
  border: none;
}

.arg-legend {
  position: absolute;
  top: 10px;
  left: 12px;
  right: 12px;
  z-index: 10;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid #e8dcc8;
  border-radius: 8px;
  font-size: 11.5px;
  color: #5c4a38;
  backdrop-filter: blur(4px);
  box-shadow: 0 2px 8px rgba(192, 144, 96, 0.08);
}
.legend-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.legend-title { color: #8a7e72; font-size: 11px; font-weight: 600; }
.legend-item { font-size: 11px; padding: 1px 4px; border-radius: 4px; font-weight: 600; }
.legend-item.premise      { color: #1864ab; }
.legend-item.intermediate { color: #5f3dc4; }
.legend-item.conclusion   { color: #c92a2a; }
.legend-item.counter      { color: #c2410c; }
.legend-item.assumption   { color: #495057; }
.legend-item.rel-support     { color: #1864ab; }
.legend-item.rel-rebut       { color: #c92a2a; }
.legend-item.rel-cause       { color: #2f9e44; }
.legend-item.rel-parallel    { color: #495057; }
.legend-item.rel-progression { color: #5f3dc4; }

.arg-btn {
  margin-left: auto;
  padding: 4px 10px;
  background: #ffffff;
  border: 1px solid #e8dcc8;
  border-radius: 14px;
  color: #b07f5b;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.arg-btn:hover { background: #fbf6ee; border-color: #d4b896; }
.arg-btn.primary {
  margin-left: 6px;
  background: linear-gradient(135deg, #fff8f0, #ffecd2);
  border-color: #d4a76a;
  color: #8b5e3c;
}
.arg-btn.primary:hover {
  background: linear-gradient(135deg, #ffecd2, #ffdab9);
  border-color: #b07f5b;
}

.arg-flow {
  width: 100%;
  height: 100%;
}

/* 浅色主题调整 vue-flow 的控件颜色 */
:deep(.vue-flow__controls) {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #e8dcc8;
  border-radius: 6px;
  box-shadow: 0 4px 14px rgba(192, 144, 96, 0.15);
}
:deep(.vue-flow__controls-button) {
  background: transparent;
  border-bottom: 1px solid #e8dcc8;
  color: #5c4a38;
}
:deep(.vue-flow__controls-button:hover) {
  background: #fbf6ee;
}
:deep(.vue-flow__controls-button svg) {
  fill: #5c4a38;
}
:deep(.vue-flow__minimap) {
  background: rgba(255, 253, 249, 0.92) !important;
  border: 1px solid #e8dcc8;
  border-radius: 6px;
}
:deep(.vue-flow__edge-text) {
  font-family: inherit;
}
:deep(.vue-flow__node.selected) {
  outline: 2px solid #ffd43b;
  outline-offset: 2px;
}
:deep(.vue-flow__node) {
  cursor: grab;
}
:deep(.vue-flow__node:active) {
  cursor: grabbing;
}
</style>
