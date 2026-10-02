import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowUp, MessageSquarePlus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { AnswerMessage } from '../components/AnswerMessage'
import { LibrarySelector } from '../components/LibrarySelector'
import { LazyPdfViewer as PdfViewer, type ViewerTarget } from '../components/LazyPdfViewer'
import { Spinner } from '../components/ui'
import { del, get, streamChat } from '../lib/api'
import type { ChatEvent, ChatMessage, Citation, Conversation } from '../lib/types'

const EXAMPLES = [
  'Summarise the key findings across the most recent reports.',
  'How has the outlook on margins changed over time?',
  'What risks do the reports highlight most often?',
]

export function Chat() {
  const { me } = useAuth()
  const labels = me?.labels ?? []
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const conversationId = params.get('c')

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [viewer, setViewer] = useState<ViewerTarget | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  // Set while a stream creates a conversation, so the URL change doesn't reload it.
  const streamedConversation = useRef<string | null>(null)

  // Default to every library the user can access.
  useEffect(() => {
    if (labels.length && selected.length === 0 && !conversationId) setSelected(labels.map((l) => l.id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [labels.length])

  const conversations = useQuery({
    queryKey: ['conversations'],
    queryFn: () => get<Conversation[]>('/conversations'),
  })

  const loadedConversation = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => get<Conversation & { messages: ChatMessage[] }>(`/conversations/${conversationId}`),
    enabled: !!conversationId && streamedConversation.current !== conversationId,
  })

  useEffect(() => {
    const data = loadedConversation.data
    if (!data) return
    setMessages(data.messages.map((m) => ({ ...m, status: 'done' as const })))
    const allowed = new Set(labels.map((l) => l.id))
    const restored = data.label_ids.filter((id) => allowed.has(id))
    if (restored.length) setSelected(restored)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedConversation.data])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  useEffect(() => () => abortRef.current?.abort(), [])

  const newChat = () => {
    abortRef.current?.abort()
    streamedConversation.current = null
    setMessages([])
    setViewer(null)
    setParams({})
  }

  const updateLast = (fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((prev) => [...prev.slice(0, -1), fn(prev[prev.length - 1])])

  const handleEvent = (event: ChatEvent) => {
    switch (event.type) {
      case 'conversation':
        if (event.conversation_id !== conversationId) {
          streamedConversation.current = event.conversation_id
          setParams({ c: event.conversation_id }, { replace: true })
        }
        break
      case 'plan':
        updateLast((m) => ({ ...m, status: 'retrieving' }))
        break
      case 'sources':
        updateLast((m) => ({ ...m, sources: event.sources, status: 'answering' }))
        break
      case 'delta':
        updateLast((m) => ({ ...m, content: m.content + event.text, status: 'answering' }))
        break
      case 'evaluating':
        updateLast((m) => ({ ...m, status: 'evaluating' }))
        break
      case 'regenerate':
        updateLast((m) => ({ ...m, content: '', status: 'regenerating' }))
        break
      case 'final':
        updateLast((m) => ({
          ...m,
          id: event.message_id ?? undefined,
          content: event.answer,
          citations: event.citations,
          eval: event.eval,
          status: 'done',
        }))
        break
      case 'error':
        updateLast((m) => ({ ...m, content: m.content || event.message, status: 'error' }))
        break
    }
  }

  const ask = async (question: string) => {
    if (!question.trim() || streaming || selected.length === 0) return
    setInput('')
    setStreaming(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question, citations: [], eval: null },
      { role: 'assistant', content: '', citations: [], eval: null, status: 'planning' },
    ])
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await streamChat({ question, conversation_id: conversationId, label_ids: selected }, handleEvent, controller.signal)
    } catch (e) {
      if (!controller.signal.aborted) {
        updateLast((m) => ({ ...m, content: (e as Error).message, status: 'error' }))
      }
    } finally {
      setStreaming(false)
      queryClient.invalidateQueries({ queryKey: ['conversations'] })
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    ask(input)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask(input)
    }
  }

  const openCitation = (c: Citation) =>
    setViewer({
      documentId: c.document_id,
      page: c.page_index,
      title: c.document_title,
      printedLabel: c.printed_label,
      snippet: c.snippet,
    })

  const removeConversation = async (id: string) => {
    await del(`/conversations/${id}`)
    if (id === conversationId) newChat()
    queryClient.invalidateQueries({ queryKey: ['conversations'] })
  }

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col gap-5 overflow-y-auto border-r border-slate-200 bg-slate-50 p-3 md:flex">
        <button
          onClick={newChat}
          className="flex items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50"
        >
          <MessageSquarePlus className="size-4" /> New question
        </button>
        <LibrarySelector labels={labels} selected={selected} onChange={setSelected} />
        <div className="space-y-1">
          <p className="px-1 text-xs font-medium uppercase tracking-wide text-slate-400">History</p>
          {conversations.isLoading && <Spinner className="mx-auto" />}
          {conversations.data?.map((c) => (
            <div
              key={c.id}
              className={clsx(
                'group flex items-center rounded-md text-sm',
                c.id === conversationId ? 'bg-white ring-1 ring-slate-200' : 'hover:bg-slate-100',
              )}
            >
              <button
                className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-slate-700"
                onClick={() => {
                  streamedConversation.current = null
                  setViewer(null)
                  setParams({ c: c.id })
                }}
                title={c.title}
              >
                {c.title}
              </button>
              <button
                className="hidden p-1.5 text-slate-400 hover:text-red-600 group-hover:block"
                onClick={() => removeConversation(c.id)}
                title="Delete"
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* Conversation */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
            {messages.length === 0 && !loadedConversation.isLoading && (
              <div className="pt-16 text-center">
                <h2 className="text-xl font-semibold">Ask across your research library</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Answers cite the report and page they come from. Click a citation to check it in the PDF.
                </p>
                <div className="mt-6 grid gap-2 sm:grid-cols-3">
                  {EXAMPLES.map((q) => (
                    <button
                      key={q}
                      onClick={() => ask(q)}
                      disabled={selected.length === 0}
                      className="rounded-lg border border-slate-200 bg-white p-3 text-left text-sm text-slate-600 hover:border-indigo-300 disabled:opacity-50"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {loadedConversation.isLoading && <Spinner className="mx-auto mt-10" />}
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-indigo-600 px-4 py-2 text-[15px] text-white">
                    {m.content}
                  </div>
                </div>
              ) : (
                <AnswerMessage key={i} message={m} onOpenCitation={openCitation} />
              ),
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        <form onSubmit={submit} className="border-t border-slate-200 bg-white p-3">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-slate-300 bg-white p-2 focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-100">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              placeholder={selected.length ? 'Ask a question about the selected libraries…' : 'Select at least one library'}
              className="max-h-40 min-h-[2.25rem] flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none"
            />
            <button
              type="submit"
              disabled={!input.trim() || streaming || selected.length === 0}
              className="flex size-9 items-center justify-center rounded-lg bg-indigo-600 text-white disabled:bg-slate-200"
              title="Send"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
          <p className="mx-auto mt-1.5 max-w-3xl text-center text-xs text-slate-400">
            Searching {selected.length} of {labels.length} libraries. AI answers can be wrong; check the cited pages.
          </p>
        </form>
      </section>

      {viewer && (
        <div className="w-[45%] min-w-[340px] shrink-0">
          <PdfViewer target={viewer} onClose={() => setViewer(null)} />
        </div>
      )}
    </div>
  )
}
