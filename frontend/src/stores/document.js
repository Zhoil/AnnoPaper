import { defineStore } from 'pinia'
import axios from 'axios'

export const useDocumentStore = defineStore('document', {
  state: () => ({
    currentDocument: null,
    loading: false,
    error: null,
    uploadProgress: 0,
    history: [],
    historyTotal: 0,
    apiProvider: 'deepseek',   // 当前选择的 API 提供商: 'deepseek' | 'qwen' | 'pipellm'
    apiModel: '',               // 前端指定的具体模型名（空串表示使用 provider 默认模型）
    availableProviders: []      // 从后端获取的可用 provider 列表
  }),

  actions: {
    // 上传文件
    async uploadFile(file) {
      this.loading = true
      this.error = null
      this.uploadProgress = 0

      try {
        const formData = new FormData()
        formData.append('file', file)
        formData.append('api_provider', this.apiProvider)  // 传递 API 提供商
        if (this.apiModel) {
          formData.append('api_model', this.apiModel)  // 传递具体模型
        }

        const response = await axios.post('/api/upload', formData, {
          onUploadProgress: (progressEvent) => {
            this.uploadProgress = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total
            )
          }
        })

        if (response.data.success) {
          this.currentDocument = response.data
          return response.data
        } else {
          throw new Error(response.data.error || '上传失败')
        }
      } catch (error) {
        this.error = error.response?.data?.error || error.message || '上传失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    // 上传URL
    async uploadUrl(url) {
      this.loading = true
      this.error = null

      try {
        const response = await axios.post('/api/upload-url', {
          url,
          api_provider: this.apiProvider,  // 传递 API 提供商
          ...(this.apiModel ? { api_model: this.apiModel } : {})  // 传递具体模型
        })

        if (response.data.success) {
          this.currentDocument = response.data
          return response.data
        } else {
          throw new Error(response.data.error || '解析失败')
        }
      } catch (error) {
        this.error = error.response?.data?.error || error.message || '解析失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    // 获取历史记录
    async fetchHistory(page = 1, perPage = 10) {
      try {
        const response = await axios.get('/api/history', {
          params: { page, per_page: perPage }
        })

        if (response.data.success) {
          this.history = response.data.history
          this.historyTotal = response.data.total
          return response.data
        }
      } catch (error) {
        this.error = error.response?.data?.error || '获取历史记录失败'
        throw error
      }
    },

    // 获取历史记录详情
    async fetchHistoryDetail(recordId) {
      this.loading = true
      try {
        const response = await axios.get(`/api/history/${recordId}`)

        if (response.data.success) {
          this.currentDocument = response.data.record
          return response.data.record
        }
      } catch (error) {
        this.error = error.response?.data?.error || '获取记录失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    // 删除历史记录
    async deleteHistory(recordId) {
      try {
        const response = await axios.delete(`/api/history/${recordId}`)

        if (response.data.success) {
          this.history = this.history.filter(item => item.id !== recordId)
          this.historyTotal -= 1
          return true
        }
      } catch (error) {
        this.error = error.response?.data?.error || '删除失败'
        throw error
      }
    },

    // 导出文档
    async exportDocument(recordId, format = 'docx') {
      try {
        const response = await axios.get(`/api/export/${recordId}`, {
          params: { format },
          responseType: 'blob'
        })

        // 创建下载链接
        const url = window.URL.createObjectURL(new Blob([response.data]))
        const link = document.createElement('a')
        link.href = url
        link.setAttribute('download', `analysis_${recordId}.${format}`)
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.URL.revokeObjectURL(url)

        return true
      } catch (error) {
        this.error = error.response?.data?.error || '导出失败'
        throw error
      }
    },

    // 比较文档
    async compareDocuments(recordIds) {
      this.loading = true
      try {
        const response = await axios.post('/api/compare', { record_ids: recordIds })

        if (response.data.success) {
          return response.data.comparison
        }
      } catch (error) {
        this.error = error.response?.data?.error || '比较失败'
        throw error
      } finally {
        this.loading = false
      }
    },

    // 清除当前文档
    clearCurrentDocument() {
      this.currentDocument = null
      this.uploadProgress = 0
    },

    // 清除错误
    clearError() {
      this.error = null
    },

    // 设置 API 提供商
    setApiProvider(provider) {
      this.apiProvider = provider
      // 切换 provider 时重置模型为默认
      this.apiModel = ''
      console.log(`🔄 API 提供商切换为: ${provider}`)
    },

    // 设置具体模型
    setApiModel(model) {
      this.apiModel = model
      console.log(`🎯 模型切换为: ${model}`)
    },

    // 从后端获取可用 provider 列表
    async fetchProviders() {
      try {
        const response = await axios.get('/api/providers')
        if (response.data.success) {
          this.availableProviders = response.data.providers
          return response.data.providers
        }
      } catch (error) {
        console.error('获取 provider 列表失败:', error)
      }
      return []
    },

    // 发送 AI 对话消息
    async sendChatMessage(message, chatHistory = []) {
      const doc = this.currentDocument
      let documentContext = ''

      if (doc) {
        const keypoints = (doc.keypoints || [])
          .slice(0, 5)
          .map(k => `• ${k.content}`)
          .join('\n')
        
        const summaryText = doc.summary?.conclusions?.[0] || ''

        documentContext = [
          `文档标题：${doc.title || '未知文档'}`,
          summaryText ? `文档摘要：${summaryText}` : '',
          keypoints ? `核心关键点：\n${keypoints}` : '',
          `文档内容节选：\n${(doc.content || '').substring(0, 2000)}`
        ].filter(Boolean).join('\n\n')
      }

      try {
        const response = await axios.post('/api/chat', {
          message,
          document_context: documentContext,
          chat_history: chatHistory
        })

        if (response.data.success) {
          return response.data.response
        }
        throw new Error(response.data.error || 'AI 响应失败')
      } catch (error) {
        throw new Error(error.response?.data?.error || error.message || 'AI 对话失败')
      }
    }
  },

  getters: {
    hasDocument: (state) => !!state.currentDocument,
    isLoading: (state) => state.loading,
    getError: (state) => state.error,
    getUploadProgress: (state) => state.uploadProgress,
    getCurrentDocument: (state) => state.currentDocument,
    getHistory: (state) => state.history,
    getHistoryTotal: (state) => state.historyTotal,
    getApiProvider: (state) => state.apiProvider
  }
})
