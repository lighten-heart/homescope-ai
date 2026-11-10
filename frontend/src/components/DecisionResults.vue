<script setup lang="ts">
// 详细结果组件。
import { computed, ref, watch } from 'vue'

import CandidateMap from './CandidateMap.vue'

import type {
  DecisionResult,
  ScoreBreakdown,
} from '../types/housing'

// 接收父组件传来的数据
const props = defineProps<{
  result: DecisionResult
}>()

const selectedId = ref('')

// 使用后端给出的rank对父组件返回的结果进行排序。
const evaluations = computed(() =>
  [...props.result.scoring_result.evaluations]
    .sort((a, b) => a.rank - b.rank),
)

watch(
  () => props.result,
  (result) => {
    // 当监听到父组件传入新的result时执行该操作
    selectedId.value = result.recommended_candidate_id
  },
  // 立即执行一次
  { immediate: true },
)

const selected = computed(() =>
  evaluations.value.find(
    (item) => item.candidate.id === selectedId.value,
  ),
)

// 按candidate_id关联，不能假设数组顺序一致。
const commuteOpinion = computed(() =>
  props.result.specialist_analysis
    .commute_analysis.opinions.find(
      (item) => item.candidate_id === selectedId.value,
    ),
)

const facilityOpinion = computed(() =>
  props.result.specialist_analysis
    .facility_analysis.opinions.find(
      (item) => item.candidate_id === selectedId.value,
    ),
)

const explanation = computed(() =>
  props.result.narrative.candidate_explanations.find(
    (item) => item.candidate_id === selectedId.value,
  ),
)

const mapEvidence = computed(() =>
  props.result.map_enrichment?.candidates.find(
    (item) => item.candidate_id === selectedId.value,
  ),
)

const opinions = computed(() => [
  {
    title: '通勤Agent',
    opinion: commuteOpinion.value,
  },
  {
    title: '设施Agent',
    opinion: facilityOpinion.value,
  },
])

const scoreItems: {
  key: keyof ScoreBreakdown
  label: string
}[] = [
  { key: 'rent', label: '租金' },
  { key: 'commute', label: '通勤' },
  { key: 'subway', label: '地铁距离' },
  { key: 'facilities', label: '配套设施' },
]
</script>

<template>
  <section class="panel">
    <h2>候选区域对比</h2>

    <p class="muted">
      点击区域查看详细分析。排名和分数来自后端评分算法。
    </p>

    <div class="candidate-grid">
      <button
        v-for="item in evaluations"
        :key="item.candidate.id"
        type="button"
        class="candidate-card"
        :class="{
          selected: selectedId === item.candidate.id,
        }"
        :aria-pressed="selectedId === item.candidate.id"
        @click="selectedId = item.candidate.id"
      >
        <span class="muted">第 {{ item.rank }} 名</span>

        <strong>{{ item.candidate.name }}</strong>

        <span class="total-score">
          {{ item.total_score.toFixed(2) }} 分
        </span>

        <span v-if="
          item.candidate.id === result.recommended_candidate_id
        ">
          推荐区域
        </span>

        <span>
          月租参考：{{ item.candidate.monthly_rent }} 元
        </span>

        <span>
          单程通勤：{{ item.candidate.commute_minutes }} 分钟
        </span>
      </button>
    </div>

    <p class="notice">
      候选区域和租金包含模拟数据；
      接入高德后，地理位置、通勤和设施使用地图查询结果。
    </p>
  </section>

  <section v-if="selected" class="panel">
    <h2>{{ selected.candidate.name }} · 评分与风险</h2>

    <p>{{ selected.candidate.address }}</p>

    <p>
      到所选地铁站步行距离：
      {{ selected.candidate.subway_distance_meters }} 米
    </p>

    <p class="muted">
      该距离不保证是到全局最近地铁站的距离。
    </p>

    <div
      v-for="item in scoreItems"
      :key="item.key"
      class="score-row"
    >
      <div class="score-heading">
        <span>{{ item.label }}</span>

        <span>
          {{ selected.score_breakdown[item.key].toFixed(2) }} 分
          · 权重
          {{
            (
              (result.scoring_result.weights[item.key] ?? 0)
              * 100
            ).toFixed(0)
          }}%
        </span>
      </div>

      <progress
        :value="selected.score_breakdown[item.key]"
        max="100"
        :aria-label="`${item.label}得分`"
      ></progress>
    </div>

    <h3>评分依据</h3>
    <ul>
      <li
        v-for="(text, index) in selected.reasons"
        :key="index"
      >
        {{ text }}
      </li>
    </ul>

    <h3>评分提示</h3>
    <ul v-if="selected.warnings.length">
      <li
        v-for="(text, index) in selected.warnings"
        :key="index"
      >
        {{ text }}
      </li>
    </ul>
    <p v-else class="muted">评分模块未返回额外提示。</p>
  </section>

  <section class="panel">
    <h2>专业Agent分析</h2>

    <p
      v-for="(text, index) in
        result.specialist_analysis.degradation_warnings"
      :key="index"
      class="notice warning-notice"
    >
      {{ text }}
    </p>

    <div class="expert-grid">
      <article
        v-for="item in opinions"
        :key="item.title"
        class="expert-card"
      >
        <h3>{{ item.title }}</h3>

        <template v-if="item.opinion">
          <p>风险等级：{{ item.opinion.risk_level }}</p>
          <p>{{ item.opinion.conclusion }}</p>

          <h4>优势</h4>
          <ul>
            <li
              v-for="(text, index) in item.opinion.advantages"
              :key="index"
            >
              {{ text }}
            </li>
          </ul>

          <h4>风险</h4>
          <ul v-if="item.opinion.risks.length">
            <li
              v-for="(text, index) in item.opinion.risks"
              :key="index"
            >
              {{ text }}
            </li>
          </ul>
          <p v-else class="muted">该Agent未列出额外风险。</p>
        </template>

        <p v-else class="muted">
          本条结果没有该区域的对应分析。
        </p>
      </article>
    </div>

    <article v-if="explanation" class="expert-card">
      <h3>综合决策意见</h3>

      <p>{{ explanation.recommendation_level }}</p>
      <p class="summary-text">{{ explanation.explanation }}</p>

      <h4>主要优势</h4>
      <ul>
        <li
          v-for="(text, index) in explanation.main_advantages"
          :key="index"
        >
          {{ text }}
        </li>
      </ul>

      <h4>需要权衡</h4>
      <ul>
        <li
          v-for="(text, index) in explanation.main_tradeoffs"
          :key="index"
        >
          {{ text }}
        </li>
      </ul>
    </article>
  </section>

  <CandidateMap
    :result="result"
    :selected-id="selectedId"
    @select="selectedId = $event"
  />

  <section v-if="mapEvidence" class="panel">
    <h2>当前区域的地图证据</h2>

    <p>
      采集到的设施：
      {{ mapEvidence.facilities.join('、') || '未返回设施' }}
    </p>

    <p>
      路线接口距离：{{ mapEvidence.route_distance_meters }} 米
    </p>

    <ul>
      <li
        v-for="(text, index) in mapEvidence.evidence"
        :key="index"
      >
        {{ text }}
      </li>
    </ul>
  </section>

  <section class="panel">
    <h2>整体风险与下一步</h2>

    <h3>整体风险</h3>
    <ul>
      <li
        v-for="(text, index) in result.narrative.overall_risks"
        :key="index"
      >
        {{ text }}
      </li>
    </ul>

    <h3>下一步建议</h3>
    <ul>
      <li
        v-for="(text, index) in result.narrative.next_actions"
        :key="index"
      >
        {{ text }}
      </li>
    </ul>
  </section>
</template>

