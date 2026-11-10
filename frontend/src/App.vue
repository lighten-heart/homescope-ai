<script setup lang="ts">
// 父组件负责调用后端进行决策。
// 完整父子组件的工作流程：
// 1.父组件将loading传给子组件HousingForm。
// 2.父组件接收HousingForm的submit事件。
// 3.父组件调用请求流程。
// 4.父组件将response传给子组件DecisionSummary。
import { computed, ref } from 'vue'

import HousingForm from './components/HousingForm.vue'
import DecisionSummary from './components/DecisionSummary.vue'
import DecisionResults from './components/DecisionResults.vue'
import HistoryPanel from './components/HistoryPanel.vue'

import { useHousingDecision } from './composables/useHousingDecision'

import type {
  HousingDecisionRequest,
  HousingDecisionResponse,
} from './types/housing'

import type {
  DecisionHistoryDetail,
} from './types/history'

const {
  loading,
  errorMessage,
  elapsedSeconds,
  response,
  submit,
} = useHousingDecision()

const historyBusy = ref(false)

// ref表示可以随时修改这个值
const openedHistory = ref<DecisionHistoryDetail | null>(
  null,
)

// 历史详情转换为摘要组件需要的展示结构。
// computed（）用于根据其他响应式数据（openedHistory）自动计算出一个新值
const displayedResponse = 
  computed<HousingDecisionResponse | null>(() => {
    const detail = openedHistory.value

    if (detail) {
      return {
        success: true,
        message: '正在查看已保存的历史分析快照',
        data: detail.result,
        history_id: detail.id,
        history_warning: null,
      }
    }

    return response.value
  })

const waitingText = computed(() => {
  return elapsedSeconds.value < 90
    ? '正在分析你的需求，请保持页面打开。'
    : '分析仍在进行中，地图查询和模型调用可能需要数分钟。'
})

async function handleSubmit(
  payload: HousingDecisionRequest,
) {
  if (historyBusy.value || loading.value) {
    return
  }

  openedHistory.value = null
  await submit(payload)
}

function openHistory(detail: DecisionHistoryDetail) {
  if (loading.value) {
    return
  }

  openedHistory.value = detail
}
</script>

<template>
  <main class="page">
    <header class="page-header">
      <p class="brand">HomeScope AI</p>
      <h1>找到更适合你的居住区域</h1>
      <p class="muted">
        综合预算、通勤和生活设施，辅助搬家选址。
      </p>
    </header>

    <!-- :loading将加载状态传给子组件；@submit监听子组件的提交事件。 -->
    <HousingForm
      :loading="loading || historyBusy"
      @submit="handleSubmit"
    />

    <section
      v-if="loading"
      class="panel"
      role="status"
      aria-live="polite"
    >
      <h2>正在生成推荐</h2>
      <p>{{ waitingText }}</p>
      <p class="muted">
        已等待 {{ elapsedSeconds }} 秒，请勿重复提交。
      </p>
    </section>

    <section
      v-if="errorMessage && !openedHistory"
      class="panel error-panel"
      role="alert"
    >
      <h2>本次请求未完成</h2>
      <p>{{ errorMessage }}</p>
    </section>

    <!-- 父组件向HistoryPanel传递disabled和refreshKey。 -->
    <!-- busy事件更新historyBusy，open事件交给openHistory处理。 -->
    <HistoryPanel
      :disabled="loading"
      :refresh-key="response?.history_id ?? null"
      @busy="historyBusy = $event"
      @open="openHistory"
    />

    <section v-if="openedHistory" class="panel">
      <h2>当前查看：历史分析</h2>

      <p>
        当时的工作地址：
        {{ openedHistory.request.work_address }}
      </p>

      <p>
        当时的预算：
        {{ openedHistory.request.monthly_budget }} 元
      </p>

      <p>
        当时的交通方式：
        {{ openedHistory.request.preferred_transportation }}
      </p>

      <button
        type="button"
        class="secondary-button"
        @click="openedHistory = null"
      >
        {{ response ? '返回本次分析结果' : '关闭历史详情' }}
      </button>
    </section>

    <!-- :response将父组件保存的后端决策结果传给子组件。 -->
    <template v-if="displayedResponse">
      <DecisionSummary :response="displayedResponse" />

      <DecisionResults :result="displayedResponse.data" />
    </template>

    <footer class="page-footer">
      当前为学习演示项目，候选区域与租金包含模拟数据。
      推荐结果仅供比较参考。
    </footer>
  </main>
</template>
