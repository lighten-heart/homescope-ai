// 定义了前端与后端交换数据时使用的类型约定。

import { z } from 'zod'

// 限制交通方式的取值，对应后端preferred_transportation允许的四个值。
export type Transportation =
  | '公共交通'
  | '驾车'
  | '骑行'
  | '步行'
// 定义提交需求的数据结构，对应后端HousingDecisionRequest。
export interface HousingDecisionRequest {
  city: string
  work_address: string
  monthly_budget: number
  max_commute_minutes: number
  preferred_facilities: string[]
  preferred_transportation: Transportation
  free_text_input: string
}

// 历史详情中也需要校验用户当时提交的需求
export const housingRequestSchema = z.object({
  city: z.string(),
  work_address: z.string(),
  monthly_budget: z.number().int(),
  max_commute_minutes: z.number().int(),
  preferred_facilities: z.array(z.string()),
  preferred_transportation: z.enum([
    '公共交通',
    '驾车',
    '骑行',
    '步行',
  ]),
  free_text_input: z.string(),
})

const locationSchema = z.object({
  longitude: z.number().min(-180).max(180),
  latitude: z.number().min(-90).max(90),
})

const candidateSchema = z.object({
  id: z.string(),
  city: z.string(),
  name: z.string(),
  address: z.string(),
  location: locationSchema,
  monthly_rent: z.number().nonnegative(),
  commute_minutes: z.number().nonnegative(),
  subway_distance_meters: z.number().nonnegative(),
  facilities: z.array(z.string()),
  data_source: z.enum(['mock', 'hybrid']),
})

const scoreBreakdownSchema = z.object({
  rent: z.number().min(0).max(100),
  commute: z.number().min(0).max(100),
  subway: z.number().min(0).max(100),
  facilities: z.number().min(0).max(100),
})

const candidateEvaluationSchema = z.object({
  rank: z.number().int().positive(),
  candidate: candidateSchema,
  total_score: z.number().min(0).max(100),
  score_breakdown: scoreBreakdownSchema,
  reasons: z.array(z.string()),
  warnings: z.array(z.string()),
})

const specialistOpinionSchema = z.object({
  candidate_id: z.string(),
  risk_level: z.enum(['低', '中', '高']),
  advantages: z.array(z.string()),
  risks: z.array(z.string()),
  conclusion: z.string(),
})

const candidateExplanationSchema = z.object({
  candidate_id: z.string(),
  recommendation_level: z.enum([
    '优先推荐',
    '可以考虑',
    '谨慎选择',
  ]),
  explanation: z.string(),
  main_advantages: z.array(z.string()),
  main_tradeoffs: z.array(z.string()),
})

const mapCandidateSchema = z.object({
  candidate_id: z.string(),
  location: locationSchema,
  commute_minutes: z.number().nonnegative(),
  route_distance_meters: z.number().nonnegative(),
  subway_distance_meters: z.number().nonnegative(),
  facilities: z.array(z.string()),
  evidence: z.array(z.string()),
  source: z.literal('amap_mcp'),
})

export const decisionResultSchema = z.object({
  recommended_candidate_id: z.string(),

  scoring_result: z.object({
    recommendation: z.string(),
    disclaimer: z.string(),

    weights: z.record(
      z.string(),
      z.number(),
    ),

    evaluations: z.array(candidateEvaluationSchema).min(1),
  }),

  specialist_analysis: z.object({
    commute_analysis: z.object({
      opinions: z.array(specialistOpinionSchema),
    }),

    facility_analysis: z.object({
      opinions: z.array(specialistOpinionSchema),
    }),

    degraded: z.boolean().default(false),

    degradation_warnings: z.array(
      z.string(),
    ).default([]),
  }),

  narrative: z.object({
    executive_summary: z.string(),
    candidate_explanations: z.array(
      candidateExplanationSchema,
    ),
    overall_risks: z.array(z.string()),
    next_actions: z.array(z.string()),
  }),

  map_enrichment: z.object({
    work_location: locationSchema,
    candidates: z.array(mapCandidateSchema),
  }).nullable(),

  pipeline_trace: z.array(z.string()),
  stage_durations_ms: z.record(
    z.string(),
    z.number().nonnegative(),
  ),
  total_duration_ms: z.number().nonnegative(),
  cache_hits: z.array(z.string()),
}).refine(
  (result) => {
    const ids = result.scoring_result.evaluations.map(
      (item) => item.candidate.id,
    )

    return (
      new Set(ids).size === ids.length &&
      ids.includes(result.recommended_candidate_id)
    )
  },
  {
    message: '候选区域ID重复，或推荐ID不在结果列表中',
  },
)

export const housingResponseSchema = z.object({
  success: z.literal(true),
  message: z.string(),
  data: decisionResultSchema,
  history_id: z.string().nullable(),
  history_warning: z.string().nullable(),
})

// 从校验规则推导类型，不再重复手写同一份字段。
// 根据已经定义好的Zod数据校验规则，生成相应的TS字段。一旦规则变了，类型也会随之变化
export type DecisionResult =
  z.infer<typeof decisionResultSchema>

export type HousingDecisionResponse =
  z.infer<typeof housingResponseSchema>

export type CandidateEvaluation =
  z.infer<typeof candidateEvaluationSchema>

export type SpecialistOpinion =
  z.infer<typeof specialistOpinionSchema>

export type ScoreBreakdown =
  z.infer<typeof scoreBreakdownSchema>