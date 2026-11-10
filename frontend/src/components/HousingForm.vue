<script setup lang="ts">
// 该子组件负责收集用户的表单输入以及验证类型。
import { reactive, ref } from 'vue'

import type {
  HousingDecisionRequest,
  Transportation,
} from '../types/housing'

// 父组件App.vue向子组件vue传数据
defineProps<{
  // 表示该组件需要接收一个名叫loading 的属性，且它必须是布尔类型
  loading: boolean
}>()

// 子组件向上面父组件发事件
const emit = defineEmits<{
  // 表示当前子组件可以触发一个名叫 submit 的自定义事件
  // 触发该事件时，需要携带一个 HousingDecisionRequest 类型的参数
  submit: [payload: HousingDecisionRequest]
}>()

const formError = ref('')

// 数字输入被清空时可能变成空字符串，显式允许这种编辑状态。
const form = reactive({
  city: '北京',
  work_address: '北京市海淀区中关村',
  monthly_budget: 5000 as number | '',
  max_commute_minutes: 45 as number | '',
  preferred_transportation: '公共交通' as Transportation,
  preferred_facilities: ['地铁站', '健身房'] as string[],
  free_text_input: '',
})

const transportationOptions: Transportation[] = [
  '公共交通',
  '驾车',
  '骑行',
  '步行',
]

const facilityOptions = [
  '地铁站',
  '超市',
  '医院',
  '公园',
  '健身房',
  '商场',
]

function handleSubmit() {
  formError.value = ''

  const workAddress = form.work_address.trim()
  const budget = Number(form.monthly_budget)
  const commute = Number(form.max_commute_minutes)

  if (!workAddress) {
    formError.value = '请输入工作地址。'
    return
  }

  if (
    !Number.isInteger(budget) ||
    budget < 500 ||
    budget > 100000
  ) {
    formError.value = '月租预算请输入500～100000之间的整数。'
    return
  }

  if (
    !Number.isInteger(commute) ||
    commute < 5 ||
    commute > 240
  ) {
    formError.value = '通勤时间请输入5～240之间的整数。'
    return
  }

  // 先将Form表单中的数据整理成一个普通的JS对象，再通过submit传给父组件。
  // emit用于通知父组件提交需求
  emit('submit', {
    city: form.city,
    work_address: workAddress,
    monthly_budget: budget,
    max_commute_minutes: commute,
    preferred_transportation:
      form.preferred_transportation,
    preferred_facilities: [
      ...form.preferred_facilities,
    ],
    free_text_input: form.free_text_input.trim(),
  })
}
</script>

<template>
  <!-- 监听用户提交表单的操作，然后执行handleSubmit。 -->
  <form class="panel" @submit.prevent="handleSubmit">
    <h2>填写选址需求</h2>
    <p class="muted">
        当前提供北京候选区域的选址演示。
    </p>
    <fieldset class="form-fields" :disabled="loading">
      <div class="form-grid">
        <label class="field">
          <span>城市</span>
          <!-- v-model使输入和变量同步。 -->
          <select v-model="form.city">
            <option value="北京">北京</option>
          </select>
        </label>

        <label class="field">
          <span>交通方式</span>
          <select v-model="form.preferred_transportation">
            <option
              v-for="item in transportationOptions"
              :key="item"
              :value="item"
            >
              {{ item }}
            </option>
          </select>
        </label>

        <label class="field full-width">
          <span>工作地址</span>
          <input
            v-model="form.work_address"
            type="text"
            required
            maxlength="200"
            placeholder="例如：北京市海淀区中关村"
          />
        </label>
        <label class="field">
          <span>月租预算（元）</span>
          <input
            v-model.number="form.monthly_budget"
            type="number"
            required
            min="500"
            max="100000"
            step="1"
          />
        </label>
        <label class="field">
          <span>最长单程通勤时间（分钟）</span>
          <input
            v-model.number="form.max_commute_minutes"
            type="number"
            required
            min="5"
            max="240"
            step="1"
          />
        </label>
      </div>

      <fieldset class="facility-group">
        <legend>希望附近拥有的设施</legend>

        <div class="checkbox-list">
          <!-- 循环生成设施选项。 -->
          <label
            v-for="item in facilityOptions"
            :key="item"
            class="checkbox-item"
          >
            <input
              v-model="form.preferred_facilities"
              type="checkbox"
              :value="item"
            />
            <span>{{ item }}</span>
          </label>
        </div>
      </fieldset>

      <label class="field">
        <span>补充要求</span>
        <textarea
          v-model="form.free_text_input"
          rows="4"
          maxlength="1000"
          placeholder="例如：希望环境安静，附近最好有公园"
        ></textarea>
      </label>

      <p v-if="formError" class="error-text" role="alert">
        {{ formError }}
      </p>

      <button
        class="primary-button"
        type="submit"
        :disabled="loading"
      >
        {{ loading ? '分析进行中…' : '开始选址分析' }}
      </button>
    </fieldset>
  </form>
</template>
