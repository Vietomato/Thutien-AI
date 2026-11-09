import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export type ForecastChartPoint = {
  week: string
  receipt_p25: number
  receipt_p50: number
  receipt_p75: number
  obligations: number
}

export default function ForecastChart({ data }: { data: ForecastChartPoint[] }) {
  return (
    <div className="chart-sample">
      <div className="chart-heading">
        <div>
          <p className="eyebrow">F4 · THU VÀ CHI THEO TUẦN</p>
          <h3>Kịch bản thu / chi</h3>
        </div>
        <span className="data-badge mock">FIXTURE MẪU</span>
      </div>
      <p className="muted chart-note">Ví dụ để Ân nối dữ liệu API. P25/P50/P75 là các kịch bản ngày thu, không phải khoảng tin cậy.</p>
      <div className="chart-area">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 16, left: 4, bottom: 2 }}>
            <CartesianGrid stroke="#e9ede6" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="week" tickLine={false} axisLine={false} tick={{ fill: '#7d897d', fontSize: 10 }} />
            <YAxis tickFormatter={(value: number) => `${value / 1_000_000}M`} tickLine={false} axisLine={false} tick={{ fill: '#7d897d', fontSize: 10 }} width={48} />
            <Tooltip formatter={(value) => `${Number(value).toLocaleString('vi-VN')} ₫`} />
            <Legend />
            <Line name="Thu P25" dataKey="receipt_p25" stroke="#9ab77c" strokeWidth={2} dot={{ r: 3 }} />
            <Line name="Thu P50" dataKey="receipt_p50" stroke="#2f7355" strokeWidth={2.5} dot={{ r: 3 }} />
            <Line name="Thu P75" dataKey="receipt_p75" stroke="#d2a855" strokeWidth={2} dot={{ r: 3 }} />
            <Line name="Khoản chi" dataKey="obligations" stroke="#bb755c" strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
