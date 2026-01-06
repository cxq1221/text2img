<template>
  <div class="app-shell">
    <LayoutSidebar />

    <!-- 右侧主区域 -->
    <main class="main">
      <Topbar v-model:topSearch="topSearch" />

      <section class="page-content">
        <HeroHeader />

        <PromptCard
          :active-tab="activeTab"
          :enhance="enhance"
          :prompt="prompt"
          :prompt-max="promptMax"
          :prompt-placeholder="promptPlaceholder"
          :selected-model-label="selectedModel.label"
          :selected-ratio-label="selectedRatio.label"
          :selected-count-label="selectedCount.label"
          :credits="credits"
          :status-text="statusText"
          :frontend-tip="frontendTip"
          :is-generating="isGenerating"
          @update:activeTab="value => (activeTab = value)"
          @update:enhance="value => (enhance = value)"
          @update:prompt="value => (prompt = value)"
          @generate="onGenerate"
        />

        <GallerySection
          :active-works-tab="activeWorksTab"
          :works-to-show="worksToShow"
          @update:activeWorksTab="value => (activeWorksTab = value)"
        />
      </section>
    </main>

    <!-- 底部进度提示，只保留一个实例，文案自动更新 -->
    <transition name="toast-fade">
      <div v-if="toastVisible" class="bottom-toast">
        <div class="bottom-toast-icon">ℹ</div>
        <div class="bottom-toast-body">
          <div class="bottom-toast-title">{{ toastTitle }}</div>
          <div class="bottom-toast-desc">{{ toastMessage }}</div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { reactive, computed, toRefs, onUnmounted } from "vue";
import LayoutSidebar from "./components/LayoutSidebar.vue";
import Topbar from "./components/Topbar.vue";
import HeroHeader from "./components/HeroHeader.vue";
import PromptCard from "./components/PromptCard.vue";
import GallerySection from "./components/GallerySection.vue";

const state = reactive({
  topSearch: "",
  activeTab: "text2img",
  enhance: true,
  prompt: "",
  promptMax: 1000,
  credits: 100,
  frontendTip: "",
  statusText: "",
  isGenerating: false,
  currentPromptId: "",
  toastVisible: false,
  toastTitle: "",
  toastMessage: "",
  activeWorksTab: "explore",
  models: [{ value: "flux-schnell", label: "FLUX Schnell（快速）" }],
  ratios: [
    { value: "1:1", label: "1:1" },
    { value: "16:9", label: "16:9" },
    { value: "9:16", label: "9:16" }
  ],
  counts: [
    { value: 1, label: "1 张图像" },
    { value: 4, label: "4 张图像" }
  ],
  exploreWorks: [
    {
      id: "p1",
      title: "春日草地上的小狗",
      type: "image",
      tag: "IMAGE",
      cover:
        "https://images.pexels.com/photos/2253275/pexels-photo-2253275.jpeg?auto=compress&cs=tinysrgb&w=600"
    },
    {
      id: "p2",
      title: "赛博朋克城市夜景",
      type: "image",
      tag: "IMAGE",
      cover:
        "https://images.pexels.com/photos/3404200/pexels-photo-3404200.jpeg?auto=compress&cs=tinysrgb&w=600"
    },
    {
      id: "p3",
      title: "流动蓝色抽象",
      type: "image",
      tag: "IMAGE",
      cover:
        "https://images.pexels.com/photos/2837009/pexels-photo-2837009.jpeg?auto=compress&cs=tinysrgb&w=600"
    },
    {
      id: "v1",
      title: "星空粒子动画",
      type: "video",
      tag: "VIDEO",
      cover:
        "https://images.pexels.com/photos/2832058/pexels-photo-2832058.jpeg?auto=compress&cs=tinysrgb&w=600"
    },
    {
      id: "v2",
      title: "科技光效循环",
      type: "video",
      tag: "VIDEO",
      cover:
        "https://images.pexels.com/photos/2580834/pexels-photo-2580834.jpeg?auto=compress&cs=tinysrgb&w=600"
    },
    {
      id: "p4",
      title: "梦幻渐变纹理",
      type: "image",
      tag: "IMAGE",
      cover:
        "https://images.pexels.com/photos/2680270/pexels-photo-2680270.jpeg?auto=compress&cs=tinysrgb&w=600"
    }
  ],
  myWorks: []
});

// 后端地址推断：开发环境 (5173/4173) 走 8000，生产环境同端口
const CURRENT_HOST = window.location.hostname || "localhost";
const CURRENT_PORT = window.location.port;
const BACKEND_BASE_URL =
  CURRENT_PORT === "5173" || CURRENT_PORT === "4173"
    ? `http://${CURRENT_HOST}:8000`
    : `http://${CURRENT_HOST}:${CURRENT_PORT || "8000"}`;

let pollTimer = null;

const selectedModel = computed(() => state.models[0]);
const selectedRatio = computed(() => state.ratios[0]);
const selectedCount = computed(() => state.counts[0]);

const promptPlaceholder = computed(() =>
  state.activeTab === "text2img"
    ? "描述你想要生成的画面，例如：一只在蓝色星空下飞翔的小猫，电影质感，柔和光线..."
    : "上传参考图后描述你想要的变化，目前仅展示前端界面，未接入上传功能。"
);

const worksToShow = computed(() =>
  state.activeWorksTab === "explore" ? state.exploreWorks : state.myWorks
);

let toastHideTimer = null;

function showToast(detail, title = "开始生成图像") {
  if (!detail) return;
  state.toastTitle = title;
  state.toastMessage = detail;
  state.toastVisible = true;

  // 生成中时保持显示，完成/失败后延迟隐藏
  if (toastHideTimer) {
    clearTimeout(toastHideTimer);
    toastHideTimer = null;
  }
  if (!state.isGenerating) {
    toastHideTimer = setTimeout(() => {
      state.toastVisible = false;
    }, 2600);
  }
}

function setStatus(detail, title = "生成进度") {
  // 主界面只展示简单的“生成中...”，不堆进度细节
  state.statusText = state.isGenerating ? "生成中..." : "";
  showToast(detail, title);
}

function clearPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function callBackendGenerate(promptText) {
  const url = `${BACKEND_BASE_URL}/generate`;
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ prompt: promptText })
  });

  if (!resp.ok) {
    let errorMsg = "调用后端 /generate 失败";
    try {
      const errorData = await resp.json();
      if (errorData.detail) {
        errorMsg = errorData.detail;
      }
    } catch {
      const text = await resp.text();
      if (text) {
        errorMsg = text;
      }
    }
    if (resp.status === 503) {
      errorMsg = "当前没有空闲机器，请稍后再试";
    }
    const error = new Error(errorMsg);
    if (resp.status === 503) {
      error.is503 = true;
    }
    throw error;
  }

  return await resp.json();
}

function startPollingStatus(promptId) {
  clearPolling();
  if (!promptId) return;

  setStatus("任务已提交，等待开始...");

  const doPoll = () => {
    pollStatus(promptId).catch(() => {});
  };

  doPoll();
  pollTimer = setInterval(doPoll, 1500);
}

async function pollStatus(promptId) {
  if (!promptId) return;

  try {
    const resp = await fetch(
      `${BACKEND_BASE_URL}/status/${encodeURIComponent(promptId)}`
    );
    if (!resp.ok) {
      if (resp.status === 404) {
        setStatus("任务不存在");
        clearPolling();
        state.isGenerating = false;
        return;
      }
      throw new Error(`HTTP ${resp.status}`);
    }

    const data = await resp.json();
    const status = data.status;
    const progress = data.progress || {};
    const currentNode = data.current_node;
    const message = data.message;

    if (status === "pending") {
      setStatus(message || "任务排队中...");
    } else if (status === "running") {
      const value = progress.value || 0;
      const max = progress.max || 100;
      let text = "";
      if (max > 0 && value > 0) {
        const percent = ((value / max) * 100).toFixed(1);
        text = `执行中: ${value} / ${max} (${percent}%)`;
      } else {
        text = "执行中...";
      }
      // if (currentNode) {
      //   text += ` · 节点: ${currentNode}`;
      // }
      // if (message) {
      //   text += ` · ${message}`;
      // }
      setStatus(text);
    } else if (status === "completed") {
      clearPolling();
      setStatus("任务完成，获取结果...", "生成完成");
      await fetchResult(promptId);
    } else if (status === "failed") {
      clearPolling();
      const err = data.error || "未知错误";
      state.isGenerating = false;
      setStatus(`任务失败：${err}`, "生成失败");
      state.isGenerating = false;
    }
  } catch (err) {
    setStatus(`轮询状态失败：${err.message}`);
  }
}

async function fetchResult(promptId) {
  try {
    const resp = await fetch(
      `${BACKEND_BASE_URL}/result/${encodeURIComponent(promptId)}`
    );

    if (!resp.ok) {
      if (resp.status === 400) {
        setStatus("任务尚未完成，继续等待...");
        startPollingStatus(promptId);
        return;
      }
      const text = await resp.text();
      throw new Error(text || "获取结果失败");
    }

    const data = await resp.json();
    const imageUrl = data.image_url;
    if (!imageUrl) {
      throw new Error("结果中未包含图片 URL");
    }

    state.myWorks.unshift({
      id: "backend-" + Date.now(),
      title: "生成结果：" + new Date().toLocaleTimeString(),
      type: "image",
      tag: "IMAGE",
      cover: imageUrl
    });
    state.activeWorksTab = "mine";

    state.isGenerating = false;
    setStatus("图片生成完成", "生成完成");
    state.isGenerating = false;
    if (state.credits > 0) {
      state.credits -= 1;
    }
  } catch (err) {
    state.isGenerating = false;
    setStatus(`获取结果失败：${err.message}`, "生成失败");
    state.isGenerating = false;
  }
}

async function onGenerate() {
  if (!state.prompt.trim()) {
    state.frontendTip = "请先输入提示词。";
    return;
  }

  state.frontendTip = "已接收到提示词，正在调用后端生成图片...";
  clearPolling();
  state.statusText = "";
  state.currentPromptId = "";
  state.isGenerating = true;

  try {
    const result = await callBackendGenerate(state.prompt.trim());
    const { prompt_id: promptId } = result;
    if (!promptId) {
      throw new Error("后端未返回有效的 prompt_id");
    }

    state.currentPromptId = promptId;
    setStatus("任务已提交，开始排队/执行...", "生成进度");
    startPollingStatus(promptId);
  } catch (err) {
    console.error(err);
    if (err.is503 || (err.message || "").includes("没有空闲机器")) {
      setStatus(err.message, "生成受限");
      state.frontendTip = err.message;
    } else {
      setStatus("生成请求失败：" + err.message, "生成失败");
      state.frontendTip = "生成请求失败，请稍后重试。原因：" + err.message;
    }
    state.isGenerating = false;
  }
}

const {
  topSearch,
  activeTab,
  enhance,
  prompt,
  promptMax,
  credits,
  frontendTip,
  statusText,
  isGenerating,
  activeWorksTab,
  toastVisible,
  toastTitle,
  toastMessage
} = toRefs(state);

onUnmounted(() => {
  clearPolling();
  if (toastHideTimer) {
    clearTimeout(toastHideTimer);
  }
});
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body {
  height: 100%;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  background: #f3f6fb;
  color: #111827;
}

.app-shell {
  display: flex;
  height: 100vh;
  background: radial-gradient(circle at top left, #e0f2ff 0, #f3f6fb 40%, #f3f6fb 100%);
}

/* 左侧侧边栏 */
.sidebar {
  width: 224px;
  background: #020617;
  color: #e5e7eb;
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px 16px;
}

.sidebar-logo-icon {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: linear-gradient(135deg, #22c1c3, #2563eb);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
}

.sidebar-logo-text {
  font-size: 18px;
  font-weight: 600;
}

.sidebar-nav-section-title {
  font-size: 12px;
  color: #6b7280;
  padding: 8px 10px;
}

.sidebar-nav {
  list-style: none;
}

.sidebar-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 2px;
  border-radius: 8px;
  cursor: pointer;
  color: #e5e7eb;
  font-size: 14px;
  transition: background 0.15s ease, color 0.15s ease;
}

.sidebar-nav-item-icon {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.sidebar-nav-item-active {
  background: linear-gradient(
    90deg,
    rgba(59, 130, 246, 0.18),
    rgba(56, 189, 248, 0.16)
  );
  color: #f9fafb;
}

.sidebar-nav-item-active .sidebar-nav-item-icon {
  background: rgba(15, 118, 110, 0.16);
  color: #22c1c3;
}

.sidebar-nav-item:hover:not(.sidebar-nav-item-active) {
  background: rgba(148, 163, 184, 0.16);
}

.sidebar-footer {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid rgba(31, 41, 55, 0.9);
}

.sidebar-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  color: #9ca3af;
  font-size: 13px;
}

.sidebar-footer-btn {
  margin: 6px 10px 0;
  padding: 6px 10px;
  border-radius: 8px;
  background: rgba(55, 65, 81, 0.9);
  color: #f9fafb;
  border: none;
  font-size: 13px;
  cursor: pointer;
}

.sidebar-user {
  margin-top: 12px;
  padding: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.9);
  color: #d1d5db;
  font-size: 13px;
}

.sidebar-user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 999px;
  background: #1f2937;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}

/* 右侧内容区域 */
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 16px 20px;
  overflow: hidden;
}

/* 顶部搜索栏 */
.topbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
}

.topbar-search {
  flex: 1;
  position: relative;
}

.topbar-search-input {
  width: 100%;
  height: 40px;
  padding: 0 40px;
  border-radius: 999px;
  border: 1px solid #e5e7eb;
  background: #ffffff;
  font-size: 14px;
  color: #111827;
}

.topbar-search-input::placeholder {
  color: #9ca3af;
}

.topbar-search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 16px;
  color: #9ca3af;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.topbar-icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  border: none;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  cursor: pointer;
}

.topbar-upgrade-btn {
  padding: 0 14px;
  height: 34px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #2563eb, #22c1c3);
  color: #ffffff;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.topbar-avatar {
  width: 30px;
  height: 30px;
  border-radius: 999px;
  background: #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
}

/* 主内容：头部 + 控件 + 作品区 */
.page-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f3f6fb;
  border-radius: 16px;
  padding: 20px 22px;
  box-shadow: 0 10px 40px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.hero-header {
  margin-bottom: 18px;
}

.hero-title-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.hero-title-main {
  font-size: 26px;
  font-weight: 600;
  color: #111827;
}

.hero-title-highlight {
  font-size: 26px;
  font-weight: 700;
  background: linear-gradient(120deg, #2563eb, #22c1c3);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 13px;
  color: #6b7280;
}

/* 文生图输入区域 */
.prompt-card {
  background: radial-gradient(circle at top, rgba(219, 234, 254, 0.8), #ffffff);
  border-radius: 16px;
  padding: 18px 18px 14px;
  border: 1px solid #e5e7eb;
  box-shadow: 0 12px 30px rgba(129, 140, 248, 0.12);
  margin-bottom: 18px;
}

.prompt-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.prompt-tabs {
  display: inline-flex;
  background: rgba(255, 255, 255, 0.9);
  border-radius: 999px;
  padding: 3px;
  border: 1px solid #e5e7eb;
}

.prompt-tab {
  min-width: 80px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  text-align: center;
  cursor: pointer;
  color: #4b5563;
}

.prompt-tab-active {
  background: #111827;
  color: #f9fafb;
}

.prompt-enhance {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #6b7280;
  cursor: pointer;
}

.enhance-switch {
  width: 34px;
  height: 18px;
  border-radius: 999px;
  background: #e5e7eb;
  position: relative;
  transition: background 0.15s ease;
}

.enhance-switch::after {
  content: "";
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.25);
  transition: transform 0.15s ease;
}

.enhance-switch-on {
  background: linear-gradient(135deg, #2563eb, #22c1c3);
}

.enhance-switch-on::after {
  transform: translateX(16px);
}

.prompt-input-wrapper {
  position: relative;
}

.prompt-textarea {
  width: 100%;
  min-height: 116px;
  resize: vertical;
  border-radius: 12px;
  border: 1px solid #d1d5db;
  padding: 10px 12px 26px;
  font-size: 14px;
  line-height: 1.6;
  color: #111827;
  background: rgba(255, 255, 255, 0.95);
}

.prompt-textarea::placeholder {
  color: #9ca3af;
}

.prompt-char-counter {
  position: absolute;
  right: 10px;
  bottom: 6px;
  font-size: 12px;
  color: #9ca3af;
}

.prompt-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
  gap: 10px;
}

.prompt-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.select {
  position: relative;
  min-width: 150px;
  height: 32px;
  border-radius: 999px;
  border: 1px solid #e5e7eb;
  background: #ffffff;
  padding: 0 26px 0 12px;
  font-size: 13px;
  color: #374151;
  display: flex;
  align-items: center;
  cursor: pointer;
}

.select-arrow {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  color: #9ca3af;
}

.prompt-generate-btn {
  padding: 0 22px;
  height: 34px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #2563eb, #22c1c3);
  color: #ffffff;
  font-size: 14px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.35);
  white-space: nowrap;
}

.prompt-generate-btn[disabled] {
  opacity: 0.7;
  cursor: not-allowed;
  box-shadow: none;
}

/* 底部进度提示样式 */
.bottom-toast {
  position: fixed;
  right: 32px;
  bottom: 32px;
  z-index: 2000;
  min-width: 260px;
  max-width: 360px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 14px;
  background: #ffffff;
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.25);
  font-size: 13px;
  color: #111827;
}

.bottom-toast-icon {
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #0f172a;
  color: #f9fafb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  margin-top: 2px;
}

.bottom-toast-body {
  flex: 1;
}

.bottom-toast-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.bottom-toast-desc {
  font-size: 12px;
  color: #6b7280;
}

.toast-fade-enter-active,
.toast-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.toast-fade-enter-from,
.toast-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

.credit-info {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 4px;
  text-align: right;
}

/* 作品区域 */
.section-tabs {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.section-tabs-left {
  display: inline-flex;
  gap: 10px;
  font-size: 14px;
  color: #6b7280;
}

.section-tab {
  padding-bottom: 6px;
  cursor: pointer;
}

.section-tab-active {
  color: #111827;
  font-weight: 500;
  border-bottom: 2px solid #2563eb;
}

.section-tabs-right {
  font-size: 13px;
  color: #9ca3af;
}

.gallery-scroll {
  flex: 1;
  overflow: auto;
  padding-top: 6px;
}

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  padding-bottom: 10px;
}

.gallery-card {
  border-radius: 16px;
  overflow: hidden;
  background: #0f172a;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.26);
  position: relative;
  cursor: pointer;
}

.gallery-card img {
  width: 100%;
  height: 210px;
  object-fit: cover;
  display: block;
}

.gallery-card-footer {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 8px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: #e5e7eb;
  background: linear-gradient(to top, rgba(15, 23, 42, 0.9), transparent);
}

.tag-chip {
  padding: 2px 6px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.6);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  background: rgba(15, 23, 42, 0.7);
}

.empty-tip {
  font-size: 13px;
  color: #9ca3af;
  padding: 40px 0;
  text-align: center;
}

/* 小屏适配：简单处理，优先保持布局完整 */
@media (max-width: 1024px) {
  .app-shell {
    flex-direction: column;
  }

  .sidebar {
    width: 100%;
    height: auto;
    flex-direction: row;
    overflow-x: auto;
  }

  .main {
    padding: 12px;
  }

  .page-content {
    padding: 14px;
  }

  .gallery-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .gallery-grid {
    grid-template-columns: repeat(1, minmax(0, 1fr));
  }

  .prompt-footer-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .prompt-generate-btn {
    width: 100%;
    justify-content: center;
  }
}
</style>


