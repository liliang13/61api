/** 相对时间:输入 "YYYY-MM-DD HH:MM:SS"(后端格式),返回 "5分钟前"。 */
export function relTime(s) {
  if (!s) return '从未'
  const t = new Date(String(s).replace(' ', 'T'))
  const diff = Math.floor((Date.now() - t.getTime()) / 1000)
  if (Number.isNaN(diff) || diff < 0) return s
  if (diff < 60) return `${diff}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${Math.floor(diff / 86400)}天前`
}

/** 延迟格式化:10240ms → 10.2s,320 → 320ms,空值 → '-'。 */
export function latency(ms) {
  if (ms == null) return '-'
  return ms >= 10000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

/** 成功率格式化:0.9987 → 99.9%,null → '-'。 */
export function pct(rate) {
  if (rate == null) return '-'
  return `${(rate * 100).toFixed(1)}%`
}
