<template>
  <div class="loading-overlay">
    <div class="loading-content">
      <div class="spinner-container">
        <div class="spinner"></div>
        <div class="spinner-ring"></div>
      </div>
      <h3 class="loading-title">正在分析文档...</h3>
      <p class="loading-text">{{ loadingTexts[currentTextIndex] }}</p>
      <div class="progress-dots">
        <span class="dot" :class="{ active: dotIndex === 0 }"></span>
        <span class="dot" :class="{ active: dotIndex === 1 }"></span>
        <span class="dot" :class="{ active: dotIndex === 2 }"></span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const loadingTexts = [
  '📖 正在解析文档内容...',
  '🔍 正在提取关键信息...',
  '✨ 正在生成分析报告...',
  '🎯 即将完成...'
]

const currentTextIndex = ref(0)
const dotIndex = ref(0)
let textInterval = null
let dotInterval = null

onMounted(() => {
  textInterval = setInterval(() => {
    currentTextIndex.value = (currentTextIndex.value + 1) % loadingTexts.length
  }, 2000)
  
  dotInterval = setInterval(() => {
    dotIndex.value = (dotIndex.value + 1) % 3
  }, 500)
})

onUnmounted(() => {
  if (textInterval) clearInterval(textInterval)
  if (dotInterval) clearInterval(dotInterval)
})
</script>

<style scoped>
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(58, 54, 48, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 3000;
  backdrop-filter: blur(10px);
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.loading-content {
  text-align: center;
  color: white;
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

.spinner-container {
  position: relative;
  width: 120px;
  height: 120px;
  margin: 0 auto 32px;
}

.spinner {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 80px;
  height: 80px;
  margin: -40px 0 0 -40px;
  border: 4px solid transparent;
  border-top-color: #6db8e3;
  border-right-color: #3a9fd8;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.spinner-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 100px;
  height: 100px;
  margin: -50px 0 0 -50px;
  border: 4px solid transparent;
  border-bottom-color: #6db8e3;
  border-left-color: #c09060;
  border-radius: 50%;
  animation: spin 1.5s linear infinite reverse;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-title {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 16px;
  text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
}

.loading-text {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.9);
  margin-bottom: 24px;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 0.8;
  }
  50% {
    opacity: 1;
  }
}

.progress-dots {
  display: flex;
  justify-content: center;
  gap: 12px;
}

.dot {
  width: 12px;
  height: 12px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  transition: all 0.3s ease;
}

.dot.active {
  background: white;
  transform: scale(1.3);
  box-shadow: 0 0 20px rgba(255, 255, 255, 0.8);
}
</style>
