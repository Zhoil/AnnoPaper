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
    availableProviders: [],     // 从后端获取的可用 provider 列表
    // 论证链路（Mermaid 文本 + 树结构）
    logicTree: null,
    logicLoading: false,
    // 相关文献推荐
    recommendations: { query: '', results: [], sources: {}, fromCache: false, cacheReason: '', cooldownRemaining: 0, warning: '' },
    recommendLoading: false
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

    // ── 论证链路：从后端获取 Mermaid 与树结构 ──
    async fetchLogicTree(recordId) {
      this.logicLoading = true
      try {
        const resp = await axios.get(`/api/logic/${recordId}`)
        if (resp.data.success) {
          this.logicTree = resp.data.logic
          return this.logicTree
        }
      } catch (error) {
        console.error('获取论证链路失败:', error)
      } finally {
        this.logicLoading = false
      }
      this.logicTree = null
      return null
    },

    // ── 相关文献推荐：从后端获取 LLM + 验证后的推荐结果 ──
    async fetchRecommendations(recordId, max = 6, options = {}) {
      this.recommendLoading = true
      try {
        const params = { max }
        if (options.force) params.force = 1
        if (options.provider) params.provider = options.provider
        const resp = await axios.get(`/api/recommend/${recordId}`, { params })
        if (resp.data.success) {
          this.recommendations = {
            query: resp.data.query || '',
            results: resp.data.results || [],
            sources: resp.data.sources || {},
            fromCache: !!resp.data.from_cache,
            cacheReason: resp.data.cache_reason || '',
            cooldownRemaining: resp.data.cooldown_remaining || 0,
            warning: resp.data.warning || ''
          }
          return this.recommendations
        }
      } catch (error) {
        console.error('获取相关推荐失败:', error)
      } finally {
        this.recommendLoading = false
      }
      this.recommendations = { query: '', results: [], sources: {}, fromCache: false, cacheReason: '', cooldownRemaining: 0, warning: '' }
      return this.recommendations
    },

    // 清空推荐与论证链路缓存（切换文档时调用）
    clearAuxiliary() {
      this.logicTree = null
      this.recommendations = { query: '', results: [], sources: {}, fromCache: false, cacheReason: '', cooldownRemaining: 0, warning: '' }
    },

    // 发送 AI 对话消息
    async sendChatMessage(message, chatHistory = [], options = {}) {
      const doc = this.currentDocument
      let documentContext = ''
      // 上传后会在文档对象中写入 record_id，历史详情的字段名为 id
      const analysisId = doc?.record_id ?? doc?.id ?? null
      const ragMode = options.ragMode || 'auto'

      if (doc) {
        const keypoints = (doc.keypoints || [])
          .slice(0, 5)
          .map(k => `• ${k.content}`)
          .join('\n')
        
        const summaryText = doc.summary?.conclusions?.[0] || ''

        // 文档正文内容交由后端 RAG 按问题动态拼接，前端仅传概览作为兄弟上下文
        documentContext = [
          `文档标题：${doc.title || '未知文档'}`,
          summaryText ? `文档摘要：${summaryText}` : '',
          keypoints ? `核心关键点：\n${keypoints}` : ''
        ].filter(Boolean).join('\n\n')
      }

      try {
        const response = await axios.post('/api/chat', {
          message,
          document_context: documentContext,
          chat_history: chatHistory,
          analysis_id: analysisId,
          rag_mode: ragMode
        })

        if (response.data.success) {
          return {
            content: response.data.response,
            ragUsed: !!response.data.rag_used,
            ragMode: response.data.rag_mode || 'none',
            ragHits: response.data.rag_hits || []
          }
        }
        throw new Error(response.data.error || 'AI 响应失败')
      } catch (error) {
        throw new Error(error.response?.data?.error || error.message || 'AI 对话失败')
      }
    },

    /**
     * 流式 AI 对话（SSE）—— 支持深度思考开关和实时推送
     * @param {string} message 用户消息
     * @param {Array} chatHistory 对话历史
     * @param {Object} options {ragMode, deepThinking}
     * @param {Object} callbacks {onThinking, onContent, onDone, onError, onMeta}
     */
    async sendChatMessageStream(message, chatHistory = [], options = {}, callbacks = {}) {
      const doc = this.currentDocument
      let documentContext = ''
      const analysisId = doc?.record_id ?? doc?.id ?? null
      const ragMode = options.ragMode || 'auto'
      const deepThinking = !!options.deepThinking

      if (doc) {
        const keypoints = (doc.keypoints || [])
          .slice(0, 5)
          .map(k => `\u2022 ${k.content}`)
          .join('\n')
        const summaryText = doc.summary?.conclusions?.[0] || ''
        documentContext = [
          `\u6587\u6863\u6807\u9898\uff1a${doc.title || '\u672a\u77e5\u6587\u6863'}`,
          summaryText ? `\u6587\u6863\u6458\u8981\uff1a${summaryText}` : '',
          keypoints ? `\u6838\u5fc3\u5173\u952e\u70b9\uff1a\n${keypoints}` : ''
        ].filter(Boolean).join('\n\n')
      }

      const body = JSON.stringify({
        message,
        document_context: documentContext,
        chat_history: chatHistory,
        analysis_id: analysisId,
        rag_mode: ragMode,
        deep_thinking: deepThinking,
      })

      try {
        const resp = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
        })

        if (!resp.ok) {
          const errData = await resp.json().catch(() => ({}))
          throw new Error(errData.error || `HTTP ${resp.status}`)
        }

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let currentEvent = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() // 保留未完成的行

          for (const line of lines) {
            if (line.startsWith('event:')) {
              currentEvent = line.slice(6).trim()
            } else if (line.startsWith('data:')) {
              const dataStr = line.slice(5).trim()
              try {
                const payload = JSON.parse(dataStr)
                switch (currentEvent) {
                  case 'thinking':
                    callbacks.onThinking?.(payload.text || '')
                    break
                  case 'content':
                    callbacks.onContent?.(payload.text || '')
                    break
                  case 'done':
                    callbacks.onDone?.(payload)
                    break
                  case 'error':
                    callbacks.onError?.(payload.message || '未知错误')
                    break
                  case 'meta':
                    callbacks.onMeta?.(payload)
                    break
                }
              } catch (e) {
                // JSON 解析失败，跳过
              }
              currentEvent = ''
            }
          }
        }
      } catch (error) {
        callbacks.onError?.(error.message || '流式对话失败')
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
