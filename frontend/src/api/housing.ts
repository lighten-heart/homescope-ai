// 前端接口访问层。负责:
// 1.把表单数据发送给后端。
// 2.将响应处理成成功和失败两种统一的结果

// 导入数据类型

import {
  housingResponseSchema,
} from '../types/housing'

import type {
  //发送给后端的数据
  HousingDecisionRequest,
  //后端返回的数据
  HousingDecisionResponse,
} from '../types/housing'

// 先确认一个值能按对象读取（该对象属性名称为字符串，属性值暂不知道是什么值）
function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value)
  )
}

// 把不同错误整理成一段文字
export function getErrorMessage(
  body: unknown,
  status: number,
): string {
  const fallback = `请求失败，HTTP状态码：${status}`
  // 情况一：拿不到有效对象
  if (!isRecord(body)) {
    return fallback
  }
  // 情况二：detail是字符串
  const detail = body.detail
  if (typeof detail === 'string') {
    return detail
  }
  // 情况三：detail是对象
  if (
    isRecord(detail) &&
    typeof detail.message === 'string'
  ) {
    return detail.message
  }
  // 情况四：detail是参数错误数组
  if (Array.isArray(detail)) {
    const messages = detail
      .filter(isRecord)
      .map((item) => {
        const field = Array.isArray(item.loc)
          ? item.loc
              .filter((part) => part !== 'body')
              .join('.')
          : '参数'

        const message =
          typeof item.msg === 'string'
            ? item.msg
            : '参数不合法'

        return `${field}：${message}`
      })

    if (messages.length > 0) {
      return messages.join('；')
    }
  }
  return fallback
}

// 真正执行网络请求
export async function submitHousingDecision(
  payload: HousingDecisionRequest,
  signal: AbortSignal,
): Promise<HousingDecisionResponse> {
  let response: Response
  // 1.发送POST请求
  try {
    response = await fetch(
      '/api/workflows/housing-decision',
      {
        method: 'POST',

        headers: {
          'Content-Type': 'application/json',
        },

        body: JSON.stringify(payload),

        signal,
      },
    )
  } catch (error) {
    // 将取消等待交给上层区分处理。
    if (signal.aborted) {
      throw error
    }

    throw new Error(
      '网络连接失败或连接中断。后台可能仍在处理，'
      + '请先确认服务状态和历史记录，避免重复提交。',
    )
  }
  // 2.读取JSON响应体
  let body: unknown = null

  try {
    body = await response.json()
  } catch (error) {
    if (signal.aborted) {
      throw error
    }
    // 代理错误可能没有返回JSON，保留null交给后续处理。
  }
  // 检查HTTP状态
  // fetch收到502、422等状态时不会自动抛异常。
  if (!response.ok) {
    throw new Error(
      getErrorMessage(body, response.status),
    )
  }
  const parsed = housingResponseSchema.safeParse(body)

  if (!parsed.success) {
    throw new Error(
      '服务返回的分析结果不完整或字段类型不正确，'
      + '请检查前后端数据结构是否一致。',
    )
  }

  return parsed.data
}