<template>
  <nav class="navbar">
    <div class="navbar-brand">
      <span class="logo">📝</span>
      <span class="title">AnnoPaper<em class="brand-accent">智阅</em></span>
    </div>
    
    <div class="navbar-menu">
      <!-- API 选择器 -->
      <div class="api-selector">
        <span class="api-label">分析引擎</span>
        <div class="api-toggle">
          <button
            class="api-btn"
            :class="{ active: documentStore.apiProvider === 'deepseek' }"
            @click="documentStore.setApiProvider('deepseek')"
            title="DeepSeek-R1：推理能力更强"
          >
            <span class="api-icon">🧠</span>
            DeepSeek-R1
          </button>
          <button
            class="api-btn"
            :class="{ active: documentStore.apiProvider === 'qwen' }"
            @click="documentStore.setApiProvider('qwen')"
            title="Qwen3.5-Plus：速度更快"
          >
            <span class="api-icon">⚡</span>
            Qwen3.5+
          </button>
          <button
            class="api-btn"
            :class="{ active: documentStore.apiProvider === 'pipellm' }"
            @click="selectPipeLLM"
            title="PipeLLM：第三方多模型"
          >
            <span class="api-icon">🌐</span>
            PipeLLM
          </button>
        </div>
        <!-- PipeLLM 模型下拉 -->
        <div v-if="documentStore.apiProvider === 'pipellm' && pipellmModels.length > 0" class="model-selector">
          <select
            :value="documentStore.apiModel || pipellmModels[0]"
            @change="onModelChange($event)"
            class="model-dropdown"
          >
            <option v-for="m in pipellmModels" :key="m" :value="m">{{ m }}</option>
          </select>
        </div>
      </div>

      <div class="menu-item" @click="$emit('show-upload')">
        <span class="menu-icon">📤</span>
        <span>上传文档</span>
      </div>
      
      <div class="menu-item" @click="toggleDropdown">
        <span class="menu-icon">⚙️</span>
        <span>功能</span>
        <span class="dropdown-arrow">▼</span>
        
        <Transition name="dropdown">
          <div v-if="showDropdown" class="dropdown-menu">
            <div class="dropdown-item" @click.stop="$emit('show-history')">
              📋 历史记录
            </div>
            <div class="dropdown-item" @click.stop="handleExport">
              💾 导出结果
            </div>
            <div class="dropdown-item" @click.stop="handleCompare">
              🔄 文档对比
            </div>
            <div class="dropdown-item" @click.stop="handleClear">
              🗑️ 清空当前
            </div>
          </div>
        </Transition>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useDocumentStore } from '../stores/document'
import { useToast } from '../composables/useToast.js'

const emit = defineEmits(['show-upload', 'show-history'])
const documentStore = useDocumentStore()
const showDropdown = ref(false)
const toast = useToast()

// PipeLLM 可用模型列表（从后端动态获取）
const pipellmModels = computed(() => {
  const p = documentStore.availableProviders.find(p => p.id === 'pipellm')
  return p ? p.models : []
})

// 选择 PipeLLM 时的处理
const selectPipeLLM = () => {
  documentStore.setApiProvider('pipellm')
  // 如果有可用模型且当前未选择，设为默认第一个
  if (pipellmModels.value.length > 0 && !documentStore.apiModel) {
    documentStore.setApiModel(pipellmModels.value[0])
  }
}

// 模型下拉变化
const onModelChange = (event) => {
  documentStore.setApiModel(event.target.value)
}

// 组件加载时获取 provider 列表
onMounted(() => {
  documentStore.fetchProviders()
})

const toggleDropdown = () => {
  showDropdown.value = !showDropdown.value
}

const handleExport = async () => {
  if (!documentStore.hasDocument) {
    toast.warning('请先上传并分析文档')
    return
  }
  
  const recordId = documentStore.getCurrentDocument.record_id
  const format = confirm('选择导出格式：\n确定 - Word文档\n取消 - PDF文档') ? 'docx' : 'pdf'
  
  try {
    await documentStore.exportDocument(recordId, format)
    toast.success('导出成功！')
  } catch (error) {
    toast.error('导出失败：' + error.message)
  }
  
  showDropdown.value = false
}

const handleCompare = () => {
  toast.info('文档对比功能：请先从历史记录中选择多个文档进行对比')
  showDropdown.value = false
}

const handleClear = () => {
  if (confirm('确定要清空当前分析结果吗？')) {
    documentStore.clearCurrentDocument()
  }
  showDropdown.value = false
}

// 点击外部关闭下拉菜单
document.addEventListener('click', (e) => {
  if (!e.target.closest('.menu-item')) {
    showDropdown.value = false
  }
})
</script>

<style scoped>
.navbar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 16px 40px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  backdrop-filter: blur(10px);
}

.navbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  font-size: 32px;
  animation: float 3s ease-in-out infinite;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-5px);
  }
}

.title {
  font-size: 24px;
  font-weight: 700;
  color: white;
  text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.2);
  display: flex;
  align-items: baseline;
  gap: 2px;
}

.brand-accent {
  font-style: normal;
  color: #ffd700;
  font-size: 26px;
  text-shadow: 0 0 8px rgba(255, 215, 0, 0.6);
}

.navbar-menu {
  display: flex;
  gap: 20px;
  align-items: center;
}

.menu-item {
  position: relative;
  padding: 10px 20px;
  color: white;
  font-size: 16px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.3s ease;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
}

.menu-item:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.menu-icon {
  font-size: 20px;
}

.dropdown-arrow {
  font-size: 12px;
  transition: transform 0.3s ease;
}

.menu-item:hover .dropdown-arrow {
  transform: rotate(180deg);
}

.dropdown-menu {
  position: absolute;
  top: calc(100% + 10px);
  right: 0;
  background: white;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  min-width: 200px;
  overflow: hidden;
  z-index: 100;
}

.dropdown-item {
  padding: 14px 20px;
  color: #2c3e50;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.2s ease;
  border-bottom: 1px solid #f0f0f0;
}

.dropdown-item:last-child {
  border-bottom: none;
}

.dropdown-item:hover {
  background: linear-gradient(135deg, #667eea20 0%, #764ba220 100%);
  padding-left: 28px;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.3s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.api-selector {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.1);
  padding: 6px 14px;
  border-radius: 30px;
  backdrop-filter: blur(10px);
}

.api-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.8);
  white-space: nowrap;
}

.api-toggle {
  display: flex;
  gap: 4px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 20px;
  padding: 3px;
}

.api-btn {
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.7);
  display: flex;
  align-items: center;
  gap: 5px;
  transition: all 0.25s ease;
  cursor: pointer;
  background: transparent;
}

.api-btn.active {
  background: white;
  color: #667eea;
  font-weight: 700;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

.api-btn:not(.active):hover {
  color: white;
  background: rgba(255, 255, 255, 0.15);
}

.api-icon {
  font-size: 14px;
}

.model-selector {
  margin-left: 8px;
}

.model-dropdown {
  background: rgba(0, 0, 0, 0.3);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
  transition: all 0.25s ease;
}

.model-dropdown:hover {
  border-color: rgba(255, 255, 255, 0.6);
  background: rgba(0, 0, 0, 0.4);
}

.model-dropdown option {
  background: #2c3e50;
  color: white;
}
</style>
