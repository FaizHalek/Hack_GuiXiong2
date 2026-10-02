/**
 * Incremental parser for a text/event-stream body that only uses `data:` lines.
 * Feed it decoded chunks; it returns every complete event parsed so far.
 */
export function createSseParser<T>() {
  let buffer = ''
  return (chunk: string): T[] => {
    buffer += chunk.replace(/\r\n/g, '\n')
    const events: T[] = []
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = raw
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (data) events.push(JSON.parse(data) as T)
      boundary = buffer.indexOf('\n\n')
    }
    return events
  }
}
