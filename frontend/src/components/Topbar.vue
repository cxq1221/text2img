<template>
  <header class="topbar">
    <div class="topbar-search">
      <span class="topbar-search-icon">🔍</span>
      <input
        class="topbar-search-input"
        type="text"
        placeholder="搜索模型、功能或作品"
        :value="topSearch"
        @input="onInput"
      />
    </div>
    <div class="topbar-right">
      <button class="topbar-icon-btn" title="通知">🔔</button>
      <button class="topbar-icon-btn" title="设置">⚙️</button>
      <button class="topbar-upgrade-btn">
        <span>⬆</span>
        <span>订阅升级</span>
      </button>
      <div class="topbar-avatar">U</div>
    </div>
  </header>
</template>

<script setup>
const props = defineProps({
  topSearch: {
    type: String,
    required: true
  }
});

const emit = defineEmits(["update:topSearch"]);

function onInput(event) {
  emit("update:topSearch", event.target.value);
}
</script>


