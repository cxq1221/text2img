<template>
  <section class="prompt-card">
    <div class="prompt-header-row">
      <div class="prompt-tabs">
        <div
          class="prompt-tab"
          :class="activeTab === 'text2img' ? 'prompt-tab-active' : ''"
          @click="$emit('update:activeTab', 'text2img')"
        >
          文生图
        </div>
        <div
          class="prompt-tab"
          :class="activeTab === 'img2img' ? 'prompt-tab-active' : ''"
          @click="$emit('update:activeTab', 'img2img')"
        >
          图生图
        </div>
      </div>

      <div class="prompt-enhance" @click="$emit('update:enhance', !enhance)">
        <div
          class="enhance-switch"
          :class="enhance ? 'enhance-switch-on' : ''"
        ></div>
        <span>增强</span>
      </div>
    </div>

    <div class="prompt-input-wrapper">
      <textarea
        class="prompt-textarea"
        :value="prompt"
        :maxlength="promptMax"
        :placeholder="promptPlaceholder"
        @input="onPromptInput"
      ></textarea>
      <div class="prompt-char-counter">
        {{ (prompt && prompt.length) || 0 }} / {{ promptMax }}
      </div>
    </div>

    <div class="prompt-footer-row">
      <div class="prompt-controls">
        <div class="select">
          <span>{{ selectedModelLabel }}</span>
          <span class="select-arrow">⌄</span>
        </div>

        <div class="select">
          <span>{{ selectedRatioLabel }}</span>
          <span class="select-arrow">⌄</span>
        </div>

        <div class="select">
          <span>{{ selectedCountLabel }}</span>
          <span class="select-arrow">⌄</span>
        </div>
      </div>

      <div>
        <button
          class="prompt-generate-btn"
          @click="$emit('generate')"
          :disabled="isGenerating"
        >
          <span>{{ isGenerating ? "⏳" : "⚡" }}</span>
          <span>{{ isGenerating ? "生成中..." : "生成图像" }}</span>
        </button>
        <div class="credit-info">
          剩余积分：{{ credits }}
          <span v-if="statusText"> · {{ statusText }}</span>
        </div>
      </div>
    </div>

    <div
      v-if="frontendTip"
      style="font-size: 12px; color: #9ca3af; margin-top: 6px"
    >
      {{ frontendTip }}
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  activeTab: {
    type: String,
    required: true
  },
  enhance: {
    type: Boolean,
    required: true
  },
  prompt: {
    type: String,
    required: true
  },
  promptMax: {
    type: Number,
    required: true
  },
  promptPlaceholder: {
    type: String,
    required: true
  },
  selectedModelLabel: {
    type: String,
    required: true
  },
  selectedRatioLabel: {
    type: String,
    required: true
  },
  selectedCountLabel: {
    type: String,
    required: true
  },
  credits: {
    type: Number,
    required: true
  },
  statusText: {
    type: String,
    required: false,
    default: ""
  },
  frontendTip: {
    type: String,
    required: false,
    default: ""
  },
  isGenerating: {
    type: Boolean,
    required: true
  }
});

const emit = defineEmits([
  "update:activeTab",
  "update:enhance",
  "update:prompt",
  "generate"
]);

function onPromptInput(event) {
  emit("update:prompt", event.target.value);
}
</script>


