const API_URL = import.meta.env.VITE_API_URL || ''

/** Load a shared result by its short id (free: no model is called). */
export async function loadShared(id) {
  const response = await fetch(`${API_URL}/api/v2/share/${encodeURIComponent(id)}`)
  if (!response.ok) throw new Error('This link has expired or never existed.')
  return response.json()
}

export const shareUrl = (id) => `https://www.factslap.app/c/${id}`

/**
 * Run a check and stream its steps.
 * onStep(step) is called for every pipeline step; resolves with the final result.
 * Throws an Error with a user-facing message (rate limits, budget, network…).
 */
export async function runCheck({ claim, tone }, onStep) {
  let response
  try {
    response = await fetch(`${API_URL}/api/v2/check-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ claim, tone }),
    })
  } catch {
    throw new Error("Can't reach the server. Check your connection and try again.")
  }

  if (!response.ok) {
    let message = 'Something went wrong. Please try again.'
    try {
      const body = await response.json()
      if (body.error) message = body.error
      else if (response.status === 422) message = 'Write a claim between 5 and 300 characters.'
    } catch { /* keep the generic message */ }
    throw new Error(message)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const event of events) {
      if (!event.startsWith('data: ')) continue
      let data
      try { data = JSON.parse(event.slice(6)) } catch { continue }
      if (data.type === 'step') onStep?.(data)
      else if (data.type === 'result') result = data
      else if (data.type === 'error') throw new Error(data.message || 'The check failed, please try again.')
    }
  }
  if (!result) throw new Error('The check was interrupted. Please try again.')
  return result
}
