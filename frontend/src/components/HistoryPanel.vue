// 历史列表组件
<script setup lang="ts">
import {
  onMounted,
  onUnmounted,
  ref,
  watch,
} from 'vue'

import {
  getDecisionHistory,
  listDecisionHistory,
} from '../api/history'

import type {
  DecisionHistoryDetail,
  DecisionHistorySummary,
} from '../types/history'

const props = defineProps<{
  disabled: boolean
  refreshKey: string | null
}>()

const emit = defineEmits<{
  open: [detail: DecisionHistoryDetail]
  busy: [value: boolean]
}>()

const PAGE_SIZE = 5

const items = ref<DecisionHistorySummary[]>([])
const offset = ref(0)
const hasMore = ref(false)
const busy = ref(false)
const errorMessage = ref('')

let controller: AbortController | null = null
let disposed = false

// 一旦busy有变化就将busy的值传给父组件
watch(
  busy,
  // 监听状态变化后执行的操作（向父组件传递布尔值）
  (value) => emit('busy', value),
  { flush: 'sync' },
)

function formatTime(value: string) {
  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', {
        hour12: false,
      })
}

async function perform(
  operation: (signal: AbortSignal) => Promise<void>,
) {
    if (busy.value || props.disabled) {
    return
  }

  busy.value = true
  errorMessage.value = ''

  const currentController = new AbortController()
  controller = currentController

  let timedOut = false

  const timer = window.setTimeout(() => {
    timedOut = true
    currentController.abort()
  }, 20_000)

  try {
    await operation(currentController.signal)
  } catch (error) {
    if (disposed) {
      return
    }

    errorMessage.value = timedOut
      ? '读取历史记录超时，请稍后刷新。'
      : error instanceof Error
        ? error.message
        : '读取历史记录失败。'
  } finally {
    window.clearTimeout(timer)

    controller = null
    busy.value = false
  }
}

async function loadPage(nextOffset: number) {
    await perform(async (signal) => {
        // 多取一条，用于判断是否存在下一页。
        const page = await listDecisionHistory(
            PAGE_SIZE + 1,
            nextOffset,
            signal,
        )

        if (disposed) {
            return
        }

        items.value = page.items.slice(0, PAGE_SIZE)
        hasMore.value = page.items.length > PAGE_SIZE
        offset.value = nextOffset
    })
}

async function openRecord(id: string) {
    await perform(
        async (signal) => {
            const detail = await getDecisionHistory(id, signal)

            if (!disposed) {
            emit('open', detail)
            }
        })
}

// 当onMounted组件挂载完成后执行（）内没有参数的箭头函数
onMounted(() => {
  void loadPage(0)
})

// 新分析保存成功后，刷新第一页。
// 监听refreshKey的变化，如果有变化就执行下面以value为参数的函数
watch(
  () => props.refreshKey,
  (value) => {
    if (value) {
      void loadPage(0)
    }
  },
)

onUnmounted(() => {
  disposed = true
  controller?.abort()
})
</script>

<template>
  <section class="panel">
    <div class="section-heading">
      <h2>历史记录</h2>

      <button
        type="button"
        class="secondary-button"
        :disabled="busy || disabled"
        @click="loadPage(0)"
      >
        刷新列表
      </button>
    </div>

    <p class="muted">
      打开历史只读取已保存结果，不重新调用模型或地图查询。
    </p>

    <p v-if="busy" role="status">正在读取历史记录…</p>

    <p
      v-if="errorMessage"
      class="error-text"
      role="alert"
    >
      {{ errorMessage }}
    </p>

    <p v-if="!busy && !errorMessage && !items.length">
      暂无历史记录。
    </p>

    <ul class="history-list">
      <li v-for="item in items" :key="item.id">
        <div>
          <strong>
            {{ item.city }} · 预算 {{ item.monthly_budget }} 元
          </strong>

          <p class="muted">
            {{ formatTime(item.created_at) }}
          </p>
        </div>

        <button
          type="button"
          class="secondary-button"
          :disabled="busy || disabled"
          @click="openRecord(item.id)"
        >
          查看详情
        </button>
      </li>
    </ul>

    <div class="pagination">
      <button
        type="button"
        class="secondary-button"
        :disabled="busy || disabled || offset === 0"
        @click="loadPage(Math.max(0, offset - PAGE_SIZE))"
      >
        上一页
      </button>

      <span>第 {{ Math.floor(offset / PAGE_SIZE) + 1 }} 页</span>

      <button
        type="button"
        class="secondary-button"
        :disabled="busy || disabled || !hasMore"
        @click="loadPage(offset + PAGE_SIZE)"
      >
        下一页
      </button>
    </div>
  </section>
</template>
