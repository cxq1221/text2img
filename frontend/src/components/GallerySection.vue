<template>
  <section style="flex: 1; display: flex; flex-direction: column">
    <div class="section-tabs">
      <div class="section-tabs-left">
        <div
          class="section-tab"
          :class="activeWorksTab === 'explore' ? 'section-tab-active' : ''"
          @click="$emit('update:activeWorksTab', 'explore')"
        >
          探索
        </div>
        <div
          class="section-tab"
          :class="activeWorksTab === 'mine' ? 'section-tab-active' : ''"
          @click="$emit('update:activeWorksTab', 'mine')"
        >
          我的作品
        </div>
      </div>
      <div class="section-tabs-right">共 {{ worksToShow.length }} 个作品</div>
    </div>

    <div class="gallery-scroll">
      <div v-if="!worksToShow.length" class="empty-tip">
        暂无作品，输入提示词并点击「生成图像」开始创作。
      </div>
      <div v-else class="gallery-grid">
        <article
          class="gallery-card"
          v-for="item in worksToShow"
          :key="item.id"
        >
          <img :src="item.cover" :alt="item.title" />
          <div class="gallery-card-footer">
            <span>{{ item.title }}</span>
            <span class="tag-chip">
              <span v-if="item.type === 'video'">▶</span>
              <span v-else>🖼</span>
              <span>{{ item.tag }}</span>
            </span>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  activeWorksTab: {
    type: String,
    required: true
  },
  worksToShow: {
    type: Array,
    required: true
  }
});

defineEmits(["update:activeWorksTab"]);
</script>


