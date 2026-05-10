<template>
  <div class="main-content">
    <div class="content-wrapper" :class="{ 'sidebar-hidden': !sidebarVisible }">
      <div class="left-panel">
        <button
          class="sidebar-toggle-btn"
          :title="sidebarVisible ? '隐藏右侧导航栏' : '展示右侧导航栏'"
          @click="toggleSidebar"
        >
          <svg v-if="sidebarVisible" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="16" rx="2"></rect>
            <line x1="15" y1="4" x2="15" y2="20"></line>
            <polyline points="19 9 17 12 19 15"></polyline>
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="16" rx="2"></rect>
            <line x1="15" y1="4" x2="15" y2="20"></line>
            <polyline points="17 9 19 12 17 15"></polyline>
          </svg>
        </button>
        <DocumentViewer ref="documentViewer" />
      </div>
      
      <div v-show="sidebarVisible" class="right-panel">
        <Sidebar @scroll-to="handleScrollTo" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import DocumentViewer from './DocumentViewer.vue'
import Sidebar from './Sidebar.vue'

const documentViewer = ref(null)
const sidebarVisible = ref(true)

const toggleSidebar = () => {
  sidebarVisible.value = !sidebarVisible.value
}

const handleScrollTo = (highlightId) => {
  if (documentViewer.value && documentViewer.value.scrollToHighlight) {
    documentViewer.value.scrollToHighlight(highlightId)
  }
}
</script>

<style scoped>
.main-content {
  flex: 1;
  min-height: 0;
  padding: 8px;
  overflow: hidden;
}

.content-wrapper {
  display: flex;
  gap: 8px;
  height: 100%;
  margin: 0 auto;
}

.left-panel {
  flex: 3;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(192, 144, 96, 0.12);
  border: 1px solid #d5cabb;
  overflow: hidden;
  animation: slideInLeft 0.6s ease;
  position: relative;
}

.sidebar-toggle-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 20;
  width: 34px;
  height: 34px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid #d5cabb;
  background: rgba(255, 255, 255, 0.92);
  color: #8a6a3a;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(192, 144, 96, 0.18);
  transition: all 0.2s ease;
  backdrop-filter: blur(4px);
}

.sidebar-toggle-btn:hover {
  color: #ffffff;
  background: linear-gradient(135deg, #c09060, #a87848);
  border-color: #a87848;
  box-shadow: 0 4px 14px rgba(192, 144, 96, 0.35);
  transform: translateY(-1px);
}

.sidebar-toggle-btn:active {
  transform: translateY(0);
}

.content-wrapper.sidebar-hidden .left-panel {
  flex: 1;
}

.right-panel {
  flex: 1;
  animation: slideInRight 0.6s ease;
}

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-50px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(50px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@media (max-width: 1200px) {
  .content-wrapper {
    flex-direction: column;
  }
  
  .left-panel,
  .right-panel {
    flex: none;
    width: 100%;
  }
}
</style>
