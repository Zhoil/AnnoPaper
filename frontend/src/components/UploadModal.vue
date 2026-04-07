<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal-container">
      <div class="modal-header">
        <h2 class="modal-title">📤 上传文档</h2>
        <button class="close-btn" @click="$emit('close')">✕</button>
      </div>
      
      <div class="modal-body">
        <div class="upload-tabs">
          <button 
            class="tab-button"
            :class="{ active: uploadMode === 'file' }"
            @click="uploadMode = 'file'"
          >
            📄 文件上传
          </button>
          <button 
            class="tab-button"
            :class="{ active: uploadMode === 'url' }"
            @click="uploadMode = 'url'"
          >
            🌐 网页URL
          </button>
        </div>
        
        <div v-if="uploadMode === 'file'" class="upload-area">
          <div 
            class="dropzone"
            :class="{ 'dragover': isDragging }"
            @drop.prevent="handleDrop"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @click="triggerFileInput"
          >
            <div class="dropzone-icon">📁</div>
            <div class="dropzone-text">
              <p class="primary-text">拖拽文件到此处或点击上传</p>
              <p class="secondary-text">支持 PDF、Word、HTML 格式</p>
            </div>
            <input 
              ref="fileInput"
              type="file"
              accept=".pdf,.doc,.docx,.html,.htm"
              @change="handleFileSelect"
              style="display: none"
            />
          </div>
          
          <div v-if="selectedFile" class="file-info">
            <div class="file-details">
              <span class="file-icon">📄</span>
              <div class="file-name-size">
                <div class="file-name">{{ selectedFile.name }}</div>
                <div class="file-size">{{ formatFileSize(selectedFile.size) }}</div>
              </div>
            </div>
            <button class="remove-btn" @click="selectedFile = null">🗑️</button>
          </div>
          
          <div v-if="uploadProgress > 0 && uploadProgress < 100" class="progress-bar">
            <div class="progress-fill" :style="{ width: `${uploadProgress}%` }"></div>
            <span class="progress-text">{{ uploadProgress }}%</span>
          </div>
        </div>
        
        <div v-else class="url-input-area">
          <input 
            v-model="urlInput"
            type="url"
            class="url-input"
            placeholder="请输入网页URL（如：https://example.com/article）"
            @keyup.enter="handleUrlSubmit"
          />
          <p class="url-hint">将自动抓取网页内容并进行分析</p>
        </div>
        
        <div v-if="error" class="error-message">
          ⚠️ {{ error }}
        </div>
      </div>
      
      <div class="modal-footer">
        <button class="cancel-btn" @click="$emit('close')">取消</button>
        <button 
          class="submit-btn"
          :disabled="isDisabled"
          @click="handleSubmit"
        >
          {{ isUploading ? '处理中...' : '开始分析' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useDocumentStore } from '../stores/document'

const emit = defineEmits(['close'])
const documentStore = useDocumentStore()

const uploadMode = ref('file')
const isDragging = ref(false)
const selectedFile = ref(null)
const urlInput = ref('')
const fileInput = ref(null)
const error = ref(null)

const uploadProgress = computed(() => documentStore.getUploadProgress)
const isUploading = computed(() => documentStore.isLoading)

const isDisabled = computed(() => {
  if (isUploading.value) return true
  if (uploadMode.value === 'file') return !selectedFile.value
  if (uploadMode.value === 'url') return !urlInput.value
  return true
})

const triggerFileInput = () => {
  fileInput.value?.click()
}

const handleFileSelect = (e) => {
  const file = e.target.files[0]
  if (file) {
    selectedFile.value = file
    error.value = null
  }
}

const handleDrop = (e) => {
  isDragging.value = false
  const file = e.dataTransfer.files[0]
  if (file) {
    selectedFile.value = file
    error.value = null
  }
}

const formatFileSize = (bytes) => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
}

const handleSubmit = async () => {
  error.value = null
  
  try {
    if (uploadMode.value === 'file') {
      await documentStore.uploadFile(selectedFile.value)
    } else {
      await documentStore.uploadUrl(urlInput.value)
    }
    
    emit('close')
  } catch (err) {
    error.value = err.message || '上传失败，请重试'
  }
}

const handleUrlSubmit = () => {
  if (urlInput.value && !isDisabled.value) {
    handleSubmit()
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  backdrop-filter: blur(5px);
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

.modal-container {
  background: #f5f1ea;
  border-radius: 20px;
  width: 90%;
  max-width: 600px;
  max-height: 90vh;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(192, 144, 96, 0.12);
  animation: slideUp 0.3s ease;
  border: 1px solid #d5cabb;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(50px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-header {
  padding: 24px 32px;
  border-bottom: 1px solid #d5cabb;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
}

.modal-title {
  font-size: 24px;
  font-weight: 700;
}

.close-btn {
  background: rgba(255, 255, 255, 0.2);
  color: white;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.3);
  transform: rotate(90deg);
}

.modal-body {
  padding: 32px;
  max-height: calc(90vh - 200px);
  overflow-y: auto;
  color: #3a3630;
}

.upload-tabs {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}

.tab-button {
  flex: 1;
  padding: 12px 24px;
  background: rgba(58, 159, 216, 0.04);
  color: #8a7e72;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 500;
  transition: all 0.3s ease;
}

.tab-button.active {
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
}

.tab-button:hover {
  transform: translateY(-2px);
}

.dropzone {
  border: 3px dashed #d4cec2;
  border-radius: 12px;
  padding: 60px 40px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  background: #ede7dc;
}

.dropzone.dragover {
  border-color: #3a9fd8;
  background: rgba(58,159,216,0.06);
}

.dropzone:hover {
  border-color: #3a9fd8;
  background: rgba(58,159,216,0.03);
}

.dropzone-icon {
  font-size: 64px;
  margin-bottom: 16px;
  animation: bounce 2s infinite;
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}

.primary-text {
  font-size: 18px;
  font-weight: 600;
  color: #3a3630;
  margin-bottom: 8px;
}

.secondary-text {
  font-size: 14px;
  color: #8a7e72;
}

.file-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: #f5f0e8;
  border-radius: 12px;
  margin-top: 16px;
}

.file-details {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.file-icon {
  font-size: 32px;
}

.file-name {
  font-weight: 600;
  color: #3a3630;
  margin-bottom: 4px;
}

.file-size {
  font-size: 13px;
  color: #8a7e72;
}

.remove-btn {
  background: #ff6b6b;
  color: white;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  font-size: 16px;
  transition: all 0.3s ease;
}

.remove-btn:hover {
  background: #ff5252;
  transform: scale(1.1);
}

.progress-bar {
  position: relative;
  height: 32px;
  background: #e0d8cb;
  border-radius: 16px;
  overflow: hidden;
  margin-top: 16px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  transition: width 0.3s ease;
}

.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-weight: 600;
  color: #3a3630;
}

.url-input-area {
  margin-top: 24px;
}

.url-input {
  width: 100%;
  padding: 16px;
  border: 1px solid #d5cabb;
  border-radius: 12px;
  font-size: 16px;
  transition: all 0.3s ease;
  background: #ffffff;
  color: #3a3630;
}

.url-input:focus {
  border-color: #3a9fd8;
  box-shadow: 0 0 0 3px rgba(58, 159, 216, 0.1);
}

.url-hint {
  margin-top: 12px;
  font-size: 13px;
  color: #8a7e72;
  text-align: center;
}

.error-message {
  padding: 12px 16px;
  background: rgba(211,47,47,0.06);
  color: #d32f2f;
  border-radius: 8px;
  margin-top: 16px;
  font-size: 14px;
}

.modal-footer {
  padding: 20px 32px;
  border-top: 1px solid #d5cabb;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  background: #ede7dc;
}

.cancel-btn,
.submit-btn {
  padding: 12px 32px;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  transition: all 0.3s ease;
}

.cancel-btn {
  background: #f5f0e8;
  color: #8a7e72;
}

.cancel-btn:hover {
  background: #ede6da;
}

.submit-btn {
  background: linear-gradient(135deg, #6db8e3 0%, #3a9fd8 100%);
  color: white;
}

.submit-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none !important;
}

.submit-btn:not(:disabled):hover {
  box-shadow: 0 8px 20px rgba(58, 159, 216, 0.3);
}
</style>
