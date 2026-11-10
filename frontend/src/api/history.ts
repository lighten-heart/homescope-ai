import { getErrorMessage } from './housing'

import {
  historyDetailSchema,
  historyPageSchema,
} from '../types/history'

async function getHistoryJson(
  url: string,
  signal: AbortSignal,
): Promise<unknown> {
  let response: Response

  try {
    response = await fetch(url, { signal })
  } catch (error) {
    if (signal.aborted) {
      throw error
    }

    throw new Error(
      '历史记录请求失败，请检查后端服务是否可用。',
    )
  }

  let body: unknown = null

  try {
    body = await response.json()
  } catch (error) {
    if (signal.aborted) {
      throw error
    }
  }

  if (!response.ok) {
    throw new Error(
      getErrorMessage(body, response.status),
    )
  }

  return body
}

export async function listDecisionHistory(
  limit: number,
  offset: number,
  signal: AbortSignal,
) {
    // 该函数用于构造URL中的查询参数
    const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })

  const body = await getHistoryJson(
    `/api/history?${query.toString()}`,
    signal,
  )

  const parsed = historyPageSchema.safeParse(body)

  if (!parsed.success) {
    throw new Error('历史列表数据结构不符合预期。')
  }

  return parsed.data
}

export async function getDecisionHistory(
  id: string,
  signal: AbortSignal,
) {
    const body = await getHistoryJson(
    `/api/history/${encodeURIComponent(id)}`,
    signal,
  )

  const parsed = historyDetailSchema.safeParse(body)

  if (!parsed.success) {
    throw new Error(
      '历史详情无法读取，可能与当前数据结构版本不兼容。',
    )
  }

  return parsed.data
}