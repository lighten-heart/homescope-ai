import { z } from 'zod'

import {
  decisionResultSchema,
  housingRequestSchema,
} from './housing'

const historySummarySchema = z.object({
  id: z.string(),
  created_at: z.string(),
  city: z.string(),
  monthly_budget: z.number(),
  recommended_candidate_id: z.string(),
})

export const historyPageSchema = z.object({
  items: z.array(historySummarySchema),
  limit: z.number().int(),
  offset: z.number().int(),
})

export const historyDetailSchema =
  historySummarySchema.extend({
    schema_version: z.literal(1),
    request: housingRequestSchema,
    result: decisionResultSchema,
  })

export type DecisionHistorySummary =
  z.infer<typeof historySummarySchema>

export type DecisionHistoryPage =
  z.infer<typeof historyPageSchema>

export type DecisionHistoryDetail =
  z.infer<typeof historyDetailSchema>