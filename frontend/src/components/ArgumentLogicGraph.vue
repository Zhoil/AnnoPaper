<template>
  <div class="arg-logic-wrap">
    <div v-if="!hasGraph" class="arg-empty">
      <span class="arg-empty-icon">🧠</span>
      <span class="arg-empty-text">LLM 未输出逻辑推理图</span>
      <span class="arg-empty-hint">可能因文档过短或结构不清晰</span>
    </div>
    <div v-else class="arg-canvas">
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
      </div>
      <VueFlow
        v-model:nodes="flowNodes"
        v-model:edges="flowEdges"
        :default-viewport="{ zoom: 0.9 }"
        :min-zoom="0.3"
        :max-zoom="2.0"
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
import { ref, computed, watch, onMounted } from 'vue'
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

// ---------- 自动分层布局 ----------
// 主线：premise(x=0) → intermediate(x=1) → conclusion(x=2)
// 辅线：counter / assumption 放在下方（y 偏移）
function layoutNodes(rawNodes) {
  const COL_X = { premise: 40, intermediate: 340, conclusion: 700 }
  const SUB_Y_OFFSET = 80
  const ROW_H = 120

  const groups = { premise: [], intermediate: [], conclusion: [], counter: [], assumption: [] }
  rawNodes.forEach(n => {
    const t = groups[n.type] ? n.type : 'intermediate'
    groups[t].push(n)
  })

  const positioned = []
  const putColumn = (list, baseX, yStart) => {
    const total = list.length
    list.forEach((n, i) => {
      const y = yStart + i * ROW_H - ((total - 1) * ROW_H) / 2
      positioned.push({ raw: n, x: baseX, y })
    })
  }

  const mainCenterY = 240
  putColumn(groups.premise, COL_X.premise, mainCenterY)
  putColumn(groups.intermediate, COL_X.intermediate, mainCenterY)
  putColumn(groups.conclusion, COL_X.conclusion, mainCenterY)

  // counter：放在 conclusion 上方偏右
  putColumn(groups.counter, COL_X.intermediate + 140, mainCenterY - (groups.intermediate.length + 1) * ROW_H / 2 - SUB_Y_OFFSET)
  // assumption：放在 premise 下方
  putColumn(groups.assumption, COL_X.premise + 140, mainCenterY + (groups.premise.length + 1) * ROW_H / 2 + SUB_Y_OFFSET)

  return positioned
}

function buildFlow(graph) {
  const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : []
  const rawEdges = Array.isArray(graph?.edges) ? graph.edges : []

  const positioned = layoutNodes(rawNodes)
  const nodes = positioned.map(({ raw, x, y }) => {
    const color = NODE_COLORS[raw.type] || NODE_COLORS.intermediate
    const typeLabel = TYPE_LABEL[raw.type] || '节点'
    return {
      id: raw.id,
      type: 'default',
      position: { x, y },
      data: { raw },
      label: `【${typeLabel}】${raw.label}`,
      style: {
        background: color.bg,
        color: color.text,
        border: `1.8px solid ${color.border}`,
        borderRadius: '10px',
        padding: '10px 12px',
        width: '220px',
        fontSize: '12.5px',
        lineHeight: '1.45',
        fontWeight: 600,
        boxShadow: `0 4px 14px ${color.shadow}`,
        whiteSpace: 'normal',
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

watch(() => props.graph, () => {
  rebuild()
}, { deep: true })

onMounted(() => {
  rebuild()
})
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
