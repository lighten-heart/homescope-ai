<script setup lang="ts">
// 项目的地图展示组件。
// 准备Vue工具和地图工具
import {
  onMounted,
  onUnmounted,
  ref,
  watch,
} from 'vue'

import { loadMapSDK } from '../services/amap'

import type {
  // 地图工具包，提供Map、Marker等构造器
  MapSDK,
  // 已经创建出来的一张地图
  MapInstance,
  // 已经创建出来的一个地图标记
  MarkerInstance,
} from '../services/amap'

import type { DecisionResult } from '../types/housing'

// 接收父组件传来的数据
const props = defineProps<{
  result: DecisionResult
  selectedId: string
}>()

// 向父组件发送事件
const emit = defineEmits<{
  select: [candidateId: string]
}>()

const container = ref<HTMLDivElement | null>(null)
const mapError = ref('')
const mapLoading = ref(false)

// 保存地图实例和生命周期状态
let sdk: MapSDK | null = null
let map: MapInstance | null = null
let disposed = false

// 管理数组
// 建立候选区域和地图标记的对应关系
let markerItems: {
  id: string | null
  // 高德标记对象
  marker: MarkerInstance
  // 标记显示使用的HTML元素
  element: HTMLElement
}[] = []

// 只更新标记的选中样式
function updateSelection() {
  for (const item of markerItems) {
    item.element.classList.toggle(
      'is-selected',
      item.id !== null &&
      item.id === props.selectedId,
    )
  }
}

// 移除上一份结果的标记
function clearMarkers() {
  if (map && markerItems.length) {
    // 把它们从地图中移除
    map.remove(
      // 从管理数组中提取全部高德标记对象
      markerItems.map((item) => item.marker),
    )
  }

  // 清空本组件保存的标记引用
  markerItems = []
}

// 根据当前结果绘制所有标记
function renderMarkers() {
  if (!map || !sdk) {
    return
  }
  // 清除旧标记
  clearMarkers()

  // 读取父组件传来的结果（地图数据）
  const enrichment = props.result.map_enrichment

  if (!enrichment) {
    return
  }

  // 统一创建一个标记
  function addMarker(
    id: string | null,
    title: string,
    longitude: number,
    latitude: number,
  ) {
    // 嵌套函数单独检查SDK，确保创建标记时它不为空。
    if (!sdk) {
      return
    }
    // 创建一个div
    const element = document.createElement('div')

    // 根据标记用途设置样式
    element.className = id === null
    ? 'map-marker work-marker'
    : 'map-marker'

    // 填入显示文字
    element.textContent = title

    // 创建高德标记
    const marker = new sdk.Marker({
      position: [longitude, latitude],
      content: element,
      title,
      anchor: 'bottom-center',
    })

    // 为创建好的标记注册候选区域的点击事件
    if (id !== null) {
      marker.on('click', () => {
        if (!disposed) {
          emit('select', id)
        }
      })
    }

    // 保存关联信息
    markerItems.push({
      id,
      marker,
      element,
    })
  }

  // 添加工作地点
  addMarker(
  null,
  '工作地点',
  enrichment.work_location.longitude,
  enrichment.work_location.latitude,
  )
  
  // 添加候选区域
  const evaluations = props.result.scoring_result.evaluations

  for (const candidate of enrichment.candidates) {
    const evaluation = evaluations.find(
      (item) =>
      item.candidate.id === candidate.candidate_id,
    )
    const title = evaluation
      ? `${evaluation.rank}. ${evaluation.candidate.name}`
      : candidate.candidate_id

    addMarker(
      candidate.candidate_id,
      title,
      candidate.location.longitude,
      candidate.location.latitude,
    )
  }

  // 一次性把创建好的标记加入地图，并调整视野
  map.add(
    markerItems.map((item) => item.marker),
  )

  // 应用当前区域的高亮样式
  updateSelection()
  map.setFitView()
}

//加载SDK并创建地图
async function initialize() {
  // 保护条件
  if (
    disposed ||
    map ||
    mapLoading.value ||
    !props.result.map_enrichment ||
    !container.value
  ) {
    return
  }

  mapLoading.value = true
  mapError.value = ''

  let timer: number | undefined

  try {
    // 二十秒后失败
    const timeout = new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => {
        reject(new Error('地图SDK加载超时。'))
      }, 20_000)
    })

    const loadedSDK = await Promise.race([
      loadMapSDK(),
      timeout,
    ])

    if (disposed || !container.value) {
      return
    }

    // 保存SDK
    sdk = loadedSDK

    // 创建地图实例
    map = new sdk.Map(container.value, {
      zoom: 11,
      viewMode: '2D',
    })

    renderMarkers()
  } catch (error) {
    if (!disposed) {
      mapError.value = error instanceof Error
        ? error.message
        : '地图加载失败。'
    }
  } finally {
    if (timer !== undefined) {
      window.clearTimeout(timer)
    }

    mapLoading.value = false
  }
}

// 首次挂载
onMounted(() => {
  void initialize()
})

// 结果变化
watch(
  () => props.result,
  () => {
    if (map) {
      // 根据当前结果绘制所有标记
      renderMarkers()
    } else {
      void initialize()
    }
  },
)

watch(
  () => props.selectedId,
  updateSelection,
)

// 组件卸载
onUnmounted(() => {
  disposed = true
  map?.destroy()
  map = null
  markerItems = []
})

</script>

<template>
  <section class="panel">
    <h2>工作地点与候选区域</h2>
    <p
      v-if="!result.map_enrichment"
      class="notice"
    >
      本条结果没有真实地图增强数据，暂不绘制位置。
    </p>

    <template v-else>
      <p class="muted">
        蓝色为候选区域，绿色为当前选中区域，
        深色为工作地点。点击区域标记可切换详细分析。
      </p>

      <p v-if="mapLoading" role="status">
        正在加载地图…
      </p>

      <!-- mapError有值时显示错误提示。注释应放在开始标签外面。 -->
      <p
        v-if="mapError"
        class="error-text"
        role="alert"
      >
        {{ mapError }}
        请检查网页地图配置和网络，修正后刷新页面。
        评分和历史记录仍可查看。
      </p>
    </template>

    <div
      ref="container"
      class="candidate-map"
      v-show="result.map_enrichment && !mapError"
      aria-label="工作地点与候选区域地图"
    ></div>

    <p class="muted">
      标记为区域代表点。本阶段展示位置，
      暂不绘制通勤路线。
    </p>
  </section>
</template>
