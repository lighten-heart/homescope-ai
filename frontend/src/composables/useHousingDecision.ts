// 分析请求状态管理模块，负责协调一次选址分析从开始到结束的过程：
// 1.提交需求。2.进入加载状态、开始计时。3.调用后端接口。4.成功（保存结果）/失败（保存错误提示）。5.结束加载、清理计时器
import { onUnmounted, ref } from 'vue'

import { submitHousingDecision } from '../api/housing'

import type {
  HousingDecisionRequest,
  HousingDecisionResponse,
} from '../types/housing'
// 前端最多等待15分钟。
// 设置浏览器等待上限。
const WAIT_TIMEOUT_MS = 15 * 60 * 1000

// 封装一套可复用的请求状态
export function useHousingDecision() {
    // 四个ref：页面关心的状态
    const loading = ref(false)
    const errorMessage = ref('')
    const elapsedSeconds = ref(0)
    const response = ref<HousingDecisionResponse | null>(
        null,
    )
    // 三个普通变量：管理请求和计时器
    let controller: AbortController | null = null
    let clockTimer: number | undefined
    let timeoutTimer: number | undefined

    // 统一清理计时器
    function clearTimers() {
        // 停止每秒更新一次的计时任务
        if (clockTimer !== undefined) {
            window.clearInterval(clockTimer)
            clockTimer = undefined
        }
        // 取消尚未触发的超时任务
        if (timeoutTimer !== undefined) {
            window.clearTimeout(timeoutTimer)
            timeoutTimer = undefined
        }
    }

    // 执行一次完整的提交过程：接收用户请求，并异步执行请求
    async function submit(
        payload: HousingDecisionRequest,
    ): Promise<void> {
    // 阻止等待期间重复提交
    if (loading.value) {
      return
    }
    // 初始化本次状态
    loading.value = true
    errorMessage.value = ''
    response.value = null
    elapsedSeconds.value = 0
    // 创建本次请求的控制器
    const currentController = new AbortController()
    controller = currentController
    // 记录开始时间
    const startedAt = Date.now()
    let timedOut = false
    // 每秒更新等待时间
    clockTimer = window.setInterval(() => {
      elapsedSeconds.value = Math.floor(
        (Date.now() - startedAt) / 1000,
      )
    }, 1000)
    // 注册超时操作
    timeoutTimer = window.setTimeout(() => {
      timedOut = true
      currentController.abort()
    }, WAIT_TIMEOUT_MS)
    // try：成功时保存结果
    try {
      response.value = await submitHousingDecision(
        payload,
        currentController.signal,
      )
    } catch (error) {
      // catch：根据失败原因设置提示
      if (timedOut) {
        errorMessage.value =
          '页面等待超时。后台任务可能仍在运行，'
          + '请先查看后端状态或历史记录，避免重复提交。'
      } else if (!currentController.signal.aborted) {
        errorMessage.value =
          error instanceof Error
            ? error.message
            : '请求失败，请检查服务状态。'
      }
    } finally {
      // finally：不论成功失败，都收尾
      elapsedSeconds.value = Math.floor(
        (Date.now() - startedAt) / 1000,
      )

      loading.value = false
      controller = null

      clearTimers()
    }
  }
  // onUnmounted：页面组件离开时清理
  onUnmounted(() => {
    controller?.abort()
    clearTimers()
  })
  // return：向页面提供状态和操作
  return {
    loading,
    errorMessage,
    elapsedSeconds,
    response,
    submit,
  }
}


