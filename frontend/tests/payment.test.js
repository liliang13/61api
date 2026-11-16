import { afterEach, describe, expect, it, vi } from 'vitest'
import { isHttpsPayUrl, startStatusPolling } from '../src/utils/payment'

afterEach(() => {
  vi.useRealTimers()
})

describe('支付链接', () => {
  it('只允许 HTTPS 地址', () => {
    expect(isHttpsPayUrl('https://pay.example.com/order')).toBe(true)
    expect(isHttpsPayUrl('http://pay.example.com/order')).toBe(false)
    expect(isHttpsPayUrl('javascript:alert(1)')).toBe(false)
    expect(isHttpsPayUrl(null)).toBe(false)
    expect(isHttpsPayUrl('not a url')).toBe(false)
  })
})

describe('支付轮询', () => {
  it('支付成功后停止轮询并通知成功', async () => {
    vi.useFakeTimers()
    const checkStatus = vi.fn().mockResolvedValue('paid')
    const onSuccess = vi.fn()
    const stop = startStatusPolling(checkStatus, { onSuccess })
    await vi.advanceTimersByTimeAsync(0)

    expect(onSuccess).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(10000)
    expect(checkStatus).toHaveBeenCalledOnce()
    stop()
  })

  it('清理后不为进行中的请求安排下一轮', async () => {
    vi.useFakeTimers()
    let resolveStatus
    const checkStatus = vi.fn(() => new Promise((resolve) => { resolveStatus = resolve }))
    const stop = startStatusPolling(checkStatus, { interval: 1000 })
    expect(checkStatus).toHaveBeenCalledOnce()

    stop()
    resolveStatus('pending')
    await vi.advanceTimersByTimeAsync(0)
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(5000)
    expect(checkStatus).toHaveBeenCalledOnce()
  })
})
