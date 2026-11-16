export function isHttpsPayUrl(value) {
  try {
    return new URL(value).protocol === 'https:'
  } catch {
    return false
  }
}

export function startStatusPolling(checkStatus, { onSuccess, onError, interval = 2500 } = {}) {
  let stopped = false
  let running = false
  let timer = null

  function stop() {
    stopped = true
    if (timer !== null) clearTimeout(timer)
    timer = null
  }

  async function tick() {
    if (stopped || running) return
    running = true
    try {
      const status = await checkStatus()
      if (stopped) return
      if (status === 'paid') {
        stop()
        await onSuccess?.()
      } else if (status !== 'pending') {
        stop()
      }
    } catch (error) {
      if (!stopped) onError?.(error)
    } finally {
      running = false
      if (!stopped) timer = setTimeout(tick, interval)
    }
  }

  void tick()
  return stop
}
