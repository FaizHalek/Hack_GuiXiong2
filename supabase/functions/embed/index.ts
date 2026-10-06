// Text embeddings with Supabase's built-in gte-small model (384 dimensions,
// English, inputs truncated at 512 tokens). Called only by the backend, which
// proves itself with the shared EMBED_SECRET header.
//
// Deploy:  supabase functions deploy embed --no-verify-jwt
//          supabase secrets set EMBED_SECRET=<long random string>
//
// Request:  POST {"texts": ["...", "..."]}   (1-16 strings)
// Response: {"embeddings": [[...384 floats], ...]}

const session = new Supabase.ai.Session('gte-small')
const SECRET = Deno.env.get('EMBED_SECRET')
const MAX_TEXTS = 16

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

Deno.serve(async (req) => {
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405)
  if (!SECRET || req.headers.get('x-embed-secret') !== SECRET) return json({ error: 'unauthorised' }, 401)

  let texts: unknown
  try {
    ;({ texts } = await req.json())
  } catch {
    return json({ error: 'invalid JSON' }, 400)
  }
  if (!Array.isArray(texts) || texts.length === 0 || texts.length > MAX_TEXTS || !texts.every((t) => typeof t === 'string')) {
    return json({ error: `texts must be an array of 1-${MAX_TEXTS} strings` }, 400)
  }

  const embeddings: number[][] = []
  for (const text of texts as string[]) {
    const vector = await session.run(text, { mean_pool: true, normalize: true })
    embeddings.push(Array.from(vector as ArrayLike<number>))
  }
  return json({ embeddings })
})
