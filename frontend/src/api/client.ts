export type PriorityItem = {
  rank: number
  invoice_id: string
  customer_id: string
  display_name: string
  due_date: string
  invoice_amount: number | string
  remaining_amount: number | string
  currency: string
  days_overdue: number
  late_rate: number | string
  late_rate_source: string
  priority_score: number | string
  eligible_for_reminder: boolean
  hold_reasons: string[]
  prediction: Record<string, unknown> | null
}

export type PriorityResponse = {
  as_of_date: string
  data_mode: 'live' | 'mock' | string
  items: PriorityItem[]
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export async function getPriority(signal?: AbortSignal): Promise<PriorityResponse> {
  const response = await fetch(`${apiBaseUrl}/api/f3/priority`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail ?? `Không tải được danh sách (HTTP ${response.status})`)
  }
  return response.json() as Promise<PriorityResponse>
}

export function getPriorityMock(): PriorityResponse {
  return {
    as_of_date: '2026-11-09',
    data_mode: 'mock',
    items: [
      {
        rank: 1,
        invoice_id: 'DEMO-001',
        customer_id: 'KH-DEMO-A',
        display_name: 'Khách hàng mẫu A',
        due_date: '2026-11-05',
        invoice_amount: 100_000_000,
        remaining_amount: 80_000_000,
        currency: 'VND',
        days_overdue: 4,
        late_rate: 0.5,
        late_rate_source: 'assumed_0.5_no_history',
        priority_score: 160_000_000,
        eligible_for_reminder: true,
        hold_reasons: [],
        prediction: { method: 'fixture', label: 'DỮ LIỆU MẪU' },
      },
      {
        rank: 2,
        invoice_id: 'DEMO-002',
        customer_id: 'KH-DEMO-B',
        display_name: 'Khách hàng mẫu B',
        due_date: '2026-11-07',
        invoice_amount: 30_000_000,
        remaining_amount: 30_000_000,
        currency: 'VND',
        days_overdue: 2,
        late_rate: 1,
        late_rate_source: 'customer_history',
        priority_score: 60_000_000,
        eligible_for_reminder: false,
        hold_reasons: ['disputed'],
        prediction: null,
      },
    ],
  }
}
