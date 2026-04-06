<template>
  <div class="app">
    <!-- Hover-triggered top navbar -->
    <div class="nav-wrapper"
         @mouseenter="navVisible = true"
         @mouseleave="navVisible = false">
      <div class="nav-trigger-strip">
        <span class="trigger-indicator">&#8964;</span>
      </div>
      <Transition name="nav-slide">
        <Navbar
          v-show="navVisible"
          @show-upload="showUploadModal = true"
          @show-history="showHistoryModal = true"
        />
      </Transition>
    </div>

    <!-- Page content (padded for trigger strip) -->
    <div class="page-content">
      <Transition name="fade">
        <div v-if="!documentStore.hasDocument" class="welcome-page">

          <!-- ░░ BLUE HERO ZONE ░░ -->
          <div class="hero-zone">
            <div class="hero-inner">
              <div class="hero-badge">✨ AI Powered Document Analyzer</div>
              <div class="hero-brand">
                <span class="hero-logo">📝</span>
                <h1 class="hero-title">
                  AnnoPaper<span class="title-accent">智阅</span>
                </h1>
              </div>
              <p class="hero-desc">基于大语言模型的智能文章分析与物理标注平台<br>上传文档，一键提取关键要点，生成带注释的 PDF</p>
              <div class="hero-actions">
                <button class="btn-primary" @click="showUploadModal = true">
                  <span>🚀</span> 立即开始分析
                </button>
                <button class="btn-secondary" @click="showHistoryModal = true">
                  <span>📋</span> 查看历史记录
                </button>
              </div>
            </div>

            <!-- S-curve double-hump wave divider（上驼峰 + 下驼峰 + 重影弧线） -->
            <div class="wave-wrapper">
              <svg class="wave-svg" viewBox="0 0 1440 160" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                <!-- Echo line 2：最远重影（最淡） -->
                <path d="M0,64 C120,64 280,9 400,9 C520,9 600,64 720,64 C840,64 920,119 1080,119 C1240,119 1360,64 1440,64"
                      fill="none" stroke="rgba(255,255,255,0.18)" stroke-width="1.5"/>
                <!-- Echo line 1：近重影（稍亮） -->
                <path d="M0,72 C120,72 280,17 400,17 C520,17 600,72 720,72 C840,72 920,127 1080,127 C1240,127 1360,72 1440,72"
                      fill="none" stroke="rgba(255,255,255,0.38)" stroke-width="1.5"/>
                <!-- 主白色填充区（S 形曲线以下 = 白色内容区） -->
                <path d="M0,80 C120,80 280,25 400,25 C520,25 600,80 720,80 C840,80 920,135 1080,135 C1240,135 1360,80 1440,80 L1440,160 L0,160 Z"
                      fill="white"/>
              </svg>
            </div>
          </div>

          <!-- ░░ WHITE CONTENT ZONE ░░ -->
          <div class="content-zone">
            <div class="content-inner">

              <!-- Feature Cards -->
              <div class="section-divider">
                <div class="divider-line"></div>
                <span class="divider-text">核心功能</span>
                <div class="divider-line"></div>
              </div>

              <section class="features-section">
                <div class="feature-card">
                  <div class="feature-icon-wrap" style="background: linear-gradient(135deg,#667eea,#764ba2)">
                    <span class="feature-icon">🧠</span>
                  </div>
                  <h3 class="feature-title">多模型 AI 分析</h3>
                  <p class="feature-desc">接入 DeepSeek-R1 深度推理、Qwen3.5-Plus 快速响应与第三方多引擎模型，精准理解文章语义，自动归纳核心论点</p>
                  <ul class="feature-list">
                    <li>DeepSeek-R1 深度推理</li>
                    <li>Qwen3.5-Plus 快速分析</li>
                    <li>多选择引擎模型与结构化要点输出</li>
                  </ul>
                </div>

                <div class="feature-card featured">
                  <div class="featured-badge">核心</div>
                  <div class="feature-icon-wrap" style="background: linear-gradient(135deg,#f093fb,#f5576c)">
                    <span class="feature-icon">🎯</span>
                  </div>
                  <h3 class="feature-title">物理坐标级标注</h3>
                  <p class="feature-desc">基于 PyMuPDF(fitz)、pdfplumber和reportlab 的三库协同文字坐标映射，在原始 PDF 上精确定位并高亮关键句，生成真实可下载的带注释文档</p>
                  <ul class="feature-list">
                    <li>坐标级精准定位</li>
                    <li>彩色分类高亮</li>
                    <li>保留原文排版</li>
                  </ul>
                </div>

                <div class="feature-card">
                  <div class="feature-icon-wrap" style="background: linear-gradient(135deg,#4facfe,#00f2fe)">
                    <span class="feature-icon">📁</span>
                  </div>
                  <h3 class="feature-title">多格式全支持</h3>
                  <p class="feature-desc">支持 PDF、Word（DOCX/DOC）、HTML 文件以及网页 URL，覆盖学术论文、技术报告、新闻资讯等多种场景</p>
                  <ul class="feature-list">
                    <li>PDF / DOCX / DOC</li>
                    <li>HTML 文件与网页 URL</li>
                    <li>跨格式统一分析</li>
                  </ul>
                </div>
              </section>

              <!-- How it works -->
              <div class="section-divider">
                <div class="divider-line"></div>
                <span class="divider-text">使用流程</span>
                <div class="divider-line"></div>
              </div>

              <section class="steps-section">
                <div class="step-item">
                  <div class="step-circle">01</div>
                  <div class="step-icon">📤</div>
                  <h4 class="step-title">上传文档</h4>
                  <p class="step-desc">支持 PDF、Word、HTML 及网页链接，自动解析文档内容</p>
                </div>
                <div class="step-connector">
                  <div class="connector-line"></div>
                  <span class="connector-arrow">▶</span>
                </div>
                <div class="step-item">
                  <div class="step-circle">02</div>
                  <div class="step-icon">🤖</div>
                  <h4 class="step-title">AI 智能分析</h4>
                  <p class="step-desc">大模型深度理解语义，提取摘要、关键论点与支撑句</p>
                </div>
                <div class="step-connector">
                  <div class="connector-line"></div>
                  <span class="connector-arrow">▶</span>
                </div>
                <div class="step-item">
                  <div class="step-circle">03</div>
                  <div class="step-icon">✍️</div>
                  <h4 class="step-title">生成标注</h4>
                  <p class="step-desc">物理坐标映射，在原始 PDF 高亮关键句并添加注释</p>
                </div>
                <div class="step-connector">
                  <div class="connector-line"></div>
                  <span class="connector-arrow">▶</span>
                </div>
                <div class="step-item">
                  <div class="step-circle">04</div>
                  <div class="step-icon">💾</div>
                  <h4 class="step-title">下载导出</h4>
                  <p class="step-desc">一键下载带高亮标注的 PDF，或导出分析报告</p>
                </div>
              </section>

              <!-- Tech Stack -->
              <section class="tech-section">
                <p class="tech-label">技术驱动</p>
                <div class="tech-tags">
                  <span class="tech-tag">🧠 DeepSeek-R1</span>
                  <span class="tech-tag">⚡ Qwen3.5-Plus</span>
                  <span class="tech-tag">🐍 Python Flask</span>
                  <span class="tech-tag">💚 Vue 3</span>
                  <span class="tech-tag">📄 pdfplumber</span>
                  <span class="tech-tag">🎨 ReportLab</span>
                  <span class="tech-tag">📑 PyMuPDF</span>
                </div>
              </section>

            </div>
          </div>

        </div>
      </Transition>

      <Transition name="slide">
        <MainContent v-if="documentStore.hasDocument" />
      </Transition>
    </div>

    <UploadModal v-if="showUploadModal" @close="showUploadModal = false" />
    <HistoryModal v-if="showHistoryModal" @close="showHistoryModal = false" />

    <Transition name="fade">
      <LoadingOverlay v-if="documentStore.isLoading" />
    </Transition>

    <!-- 全局美化提示弹窗 -->
    <ToastContainer />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useDocumentStore } from './stores/document'
import Navbar from './components/Navbar.vue'
import MainContent from './components/MainContent.vue'
import UploadModal from './components/UploadModal.vue'
import HistoryModal from './components/HistoryModal.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'
import ToastContainer from './components/ToastContainer.vue'

const documentStore = useDocumentStore()
const showUploadModal = ref(false)
const showHistoryModal = ref(false)
const navVisible = ref(false)
</script>

<style scoped>
/* ===== APP LAYOUT ===== */
.app {
  height: 100%;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f8f9ff;
}

/* ===== HOVER NAVBAR WRAPPER ===== */
.nav-wrapper {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
}

.nav-trigger-strip {
  height: 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  overflow: visible;
}

.trigger-indicator {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1;
  transition: opacity 0.3s;
}

.nav-trigger-strip:hover .trigger-indicator {
  color: white;
}

.nav-slide-enter-active,
.nav-slide-leave-active {
  transition: transform 0.3s ease, opacity 0.3s ease;
}

.nav-slide-enter-from,
.nav-slide-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}

/* ===== PAGE CONTENT ===== */
.page-content {
  flex: 1;
  min-height: 0;
  padding-top: 8px; /* trigger strip height */
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ===== WELCOME PAGE ===== */
.welcome-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

/* ===== BLUE HERO ZONE ===== */
.hero-zone {
  background: linear-gradient(160deg,
    #0c1f5c 0%,
    #12307d 25%,
    #1a4abc 55%,
    #2c5fd4 80%,
    #3d72e0 100%
  );
  position: relative;
  flex-shrink: 0;
}

.hero-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 70px 40px 60px;
  text-align: center;
}

/* ===== WAVE DIVIDER ===== */
.wave-wrapper {
  height: 160px;
  overflow: hidden;
  line-height: 0;
  margin-top: -1px;
}

.wave-svg {
  width: 100%;
  height: 100%;
  display: block;
}

/* ===== WHITE CONTENT ZONE ===== */
.content-zone {
  background: white;
  flex: 1;
}

.content-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 40px 60px;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(30px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ===== HERO SECTION (on dark blue bg) ===== */
.hero-badge {
  display: inline-block;
  padding: 6px 18px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.28);
  border-radius: 20px;
  font-size: 14px;
  color: rgba(255, 255, 255, 0.9);
  font-weight: 500;
  margin-bottom: 24px;
  letter-spacing: 0.5px;
  backdrop-filter: blur(4px);
}

.hero-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-bottom: 20px;
}

.hero-logo {
  font-size: 56px;
  animation: float 3s ease-in-out infinite;
  filter: drop-shadow(0 4px 12px rgba(0,0,0,0.3));
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50%       { transform: translateY(-8px); }
}

.hero-title {
  font-size: 64px;
  font-weight: 800;
  color: white;
  line-height: 1;
  letter-spacing: -2px;
  text-shadow: 0 2px 24px rgba(0,0,0,0.25);
}

.title-accent {
  color: #7dd3fc;
  text-shadow: 0 0 30px rgba(125, 211, 252, 0.7);
}

.hero-desc {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.78);
  line-height: 1.8;
  margin-bottom: 36px;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}

.hero-actions {
  display: flex;
  gap: 16px;
  justify-content: center;
  flex-wrap: wrap;
}

.btn-primary {
  padding: 14px 36px;
  font-size: 17px;
  font-weight: 600;
  color: #0c1f5c;
  background: white;
  border-radius: 50px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.25), 0 0 0 1px rgba(255,255,255,0.2);
  transition: all 0.3s ease;
  cursor: pointer;
}

.btn-primary:hover {
  transform: translateY(-3px);
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.35);
  background: #f0f7ff;
}

.btn-secondary {
  padding: 14px 36px;
  font-size: 17px;
  font-weight: 600;
  color: white;
  background: rgba(255, 255, 255, 0.12);
  border: 2px solid rgba(255, 255, 255, 0.38);
  border-radius: 50px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  backdrop-filter: blur(8px);
  transition: all 0.3s ease;
  cursor: pointer;
}

.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.22);
  border-color: rgba(255, 255, 255, 0.6);
  transform: translateY(-2px);
}

/* ===== SECTION DIVIDER ===== */
.section-divider {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 40px 0 32px;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #667eea40, transparent);
}

.divider-text {
  font-size: 14px;
  font-weight: 600;
  color: #9ca3af;
  letter-spacing: 2px;
  text-transform: uppercase;
  white-space: nowrap;
}

/* ===== FEATURE CARDS ===== */
.features-section {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  margin-bottom: 16px;
}

.feature-card {
  background: white;
  border-radius: 20px;
  padding: 32px 28px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
  border: 1px solid rgba(102, 126, 234, 0.1);
  transition: all 0.3s ease;
  position: relative;
  overflow: hidden;
}

.feature-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, #667eea, #764ba2);
  opacity: 0;
  transition: opacity 0.3s;
}

.feature-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 40px rgba(102, 126, 234, 0.15);
}

.feature-card:hover::before {
  opacity: 1;
}

.feature-card.featured {
  border-color: rgba(240, 147, 251, 0.3);
  background: linear-gradient(180deg, #fff, #fdf4ff);
}

.feature-card.featured::before {
  background: linear-gradient(90deg, #f093fb, #f5576c);
  opacity: 1;
}

.featured-badge {
  position: absolute;
  top: 16px;
  right: 16px;
  background: linear-gradient(135deg, #f093fb, #f5576c);
  color: white;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 12px;
  letter-spacing: 0.5px;
}

.feature-icon-wrap {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 20px;
}

.feature-icon {
  font-size: 28px;
}

.feature-title {
  font-size: 18px;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 12px;
}

.feature-desc {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.7;
  margin-bottom: 16px;
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.feature-list li {
  font-size: 13px;
  color: #667eea;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 8px;
}

.feature-list li::before {
  content: '✓';
  font-size: 12px;
  font-weight: 700;
  color: #667eea;
  background: #667eea15;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* ===== STEPS SECTION ===== */
.steps-section {
  display: flex;
  align-items: flex-start;
  gap: 0;
  margin-bottom: 48px;
  background: #f8faff;
  border-radius: 20px;
  padding: 36px 32px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
  border: 1px solid rgba(102, 126, 234, 0.08);
}

.step-item {
  flex: 1;
  text-align: center;
  padding: 0 12px;
}

.step-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  font-size: 15px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.step-icon {
  font-size: 32px;
  margin-bottom: 12px;
}

.step-title {
  font-size: 15px;
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 8px;
}

.step-desc {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.6;
}

.step-connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-top: 20px;
  gap: 4px;
  flex-shrink: 0;
  width: 40px;
}

.connector-line {
  height: 2px;
  width: 32px;
  background: linear-gradient(90deg, #667eea40, #764ba240);
}

.connector-arrow {
  font-size: 12px;
  color: #667eea80;
}

/* ===== TECH SECTION ===== */
.tech-section {
  text-align: center;
  padding: 32px 20px 16px;
}

.tech-label {
  font-size: 13px;
  color: #9ca3af;
  font-weight: 600;
  letter-spacing: 2px;
  text-transform: uppercase;
  margin-bottom: 16px;
}

.tech-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.tech-tag {
  padding: 7px 16px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  transition: all 0.2s ease;
  cursor: default;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}

.tech-tag:hover {
  border-color: #667eea;
  color: #667eea;
  background: #667eea08;
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(102,126,234,0.12);
}

/* ===== TRANSITIONS ===== */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.4s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-enter-active,
.slide-leave-active {
  transition: all 0.5s ease;
}
.slide-enter-from {
  opacity: 0;
  transform: translateY(20px);
}
.slide-leave-to {
  opacity: 0;
}

/* ===== RESPONSIVE ===== */
@media (max-width: 900px) {
  .features-section {
    grid-template-columns: 1fr;
  }
  .steps-section {
    flex-direction: column;
    align-items: center;
  }
  .step-connector {
    transform: rotate(90deg);
    padding: 0;
    margin: 4px 0;
  }
  .hero-title {
    font-size: 44px;
  }
  .hero-inner {
    padding: 50px 20px 50px;
  }
  .content-inner {
    padding: 24px 20px 40px;
  }
}
</style>
