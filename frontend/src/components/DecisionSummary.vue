// 该子组件负责接收父组件传来的结果并编写结果摘要
<script setup lang="ts">
import type {
  HousingDecisionResponse,
} from '../types/housing'

//当前子组件需要接收父组件传递来的一个名叫response的数据
defineProps<{
  response: HousingDecisionResponse
}>()
</script>

<template>
  <section class="panel result-panel">
    <h2>分析结果</h2>

    <p class="muted">
      {{ response.message }}
    </p>

    <h3>
      {{ response.data.scoring_result.recommendation }}
    </h3>

    <p class="summary-text">
      {{ response.data.narrative.executive_summary }}
    </p>

    <p class="notice">
      {{ response.data.scoring_result.disclaimer }}
    </p>

    <p v-if="response.history_id" class="history-info">
      历史记录已保存，记录编号：
      <code>{{ response.history_id }}</code>
    </p>

    <p
      v-if="response.history_warning"
      class="notice warning-notice"
      role="status"
    >
      {{ response.history_warning }}
    </p>

    <p
      v-if="!response.history_id && !response.history_warning"
      class="notice"
    >
      本次响应未提供历史记录编号，暂时无法确认是否保存。
    </p>
  </section>
</template>
