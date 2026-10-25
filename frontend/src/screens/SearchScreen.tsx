import { HourglassIcon, InfoIcon, MagnifyingGlassIcon, XCircleIcon } from '@phosphor-icons/react';
import { useMutation, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { cn } from 'cn';
import { useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

import { ApiError, askRepository, getGraph, getPlan, searchRepository } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { excerpt, queryWords, splitAtWords } from '@/lib/search';
import { GraphArea } from '@/screens/GraphScreen';
import { ModuleInspector } from '@/screens/ModuleInspector';
import type { AskResponse, GraphPayload, SearchHit, SearchMode } from '@/types/contracts';

const MODES: [SearchMode, string][] = [
  ['keyword', 'Keyword'],
  ['vector', 'Vector'],
  ['hybrid', 'Hybrid'],
];
const NOT_READY_POLL_MS = 3000;
type AskTurn = { question: string; answer: AskResponse };

type NotReady = { state?: string; index?: string; embedded?: number; total?: number | null; reason?: string | null };

// An index on its way: ask again until it lands. The backend checks before it embeds the query, so asking spends no quota.
const building = (e: unknown) =>
  e instanceof ApiError && e.code === 'SEARCH_INDEX_NOT_READY' && ['indexing', 'building'].includes(String(e.details.state));

function ranks(hit: SearchHit) {
  const rank = (n: number | null) => (n ? `#${n}` : 'no match');
  if (hit.match_method === 'keyword') return `Keyword ${rank(hit.keyword_rank)}`;
  if (hit.match_method === 'vector') return `Vector ${rank(hit.vector_rank)}`;
  // Native $rankFusion's breakdown is best effort; without it, only the fused rank is known.
  if (!hit.keyword_rank && !hit.vector_rank) return `Hybrid #${hit.rank}`;
  return `Hybrid, keyword ${rank(hit.keyword_rank)}, vector ${rank(hit.vector_rank)}`;
}

/** 503 SEARCH_INDEX_NOT_READY is an index on its way or gone, never "no results" (#20). */
function NotReadyNotice({ error, onKeyword }: { error: ApiError; onKeyword?: () => void }) {
  const d = error.details as NotReady;
  const waiting = building(error);
  return (
    <div className="m-4 flex items-start gap-2 rounded-md border bg-card px-4 py-3">
      {waiting ? (
        <HourglassIcon size={20} aria-hidden className="flex-none" />
      ) : (
        <XCircleIcon size={20} aria-hidden className="flex-none text-failed" />
      )}
      <div className="flex flex-col items-start gap-2 text-sm">
        {d.state === 'indexing' ? (
          <span>
            Index building{d.total ? `: ${d.embedded ?? 0} of ${d.total} chunks embedded` : ''}. Keyword search works now;
            these results appear when it finishes.
          </span>
        ) : d.state === 'building' ? (
          <span>The {d.index} index is still building in Atlas. These results appear when it’s ready.</span>
        ) : d.state === 'failed' ? (
          <span className="flex flex-col">
            Search indexing stopped, so vector and hybrid search are unavailable here. Keyword search still works.
            {d.reason && <span className="break-words text-muted-foreground">{d.reason}</span>}
          </span>
        ) : (
          <span>{error.message}</span>
        )}
        {onKeyword && (
          <Button variant="outline" onClick={onKeyword}>
            Search by keyword
          </Button>
        )}
      </div>
    </div>
  );
}

function Hit({ hit, words, picked, onPick }: { hit: SearchHit; words: string[]; picked: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={picked}
      onClick={onPick}
      className={cn(
        'flex w-full flex-col gap-2 border-b px-4 py-3 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring',
        picked && 'rounded-md outline-2 -outline-offset-2 outline-foreground',
      )}
    >
      <span className="flex items-baseline gap-2 text-sm">
        <span className="truncate font-mono font-medium">{hit.path}</span>
        <span className="whitespace-nowrap text-muted-foreground">
          lines {hit.start_line}–{hit.end_line}
        </span>
        <span className="ml-auto whitespace-nowrap text-muted-foreground">{ranks(hit)}</span>
      </span>
      {hit.qualified_name && <span className="truncate font-mono text-sm text-muted-foreground">{hit.qualified_name}</span>}
      <span className="block overflow-hidden rounded-sm border bg-code px-3 py-2 font-mono text-sm leading-5 whitespace-pre">
        {splitAtWords(excerpt(hit.snippet, words), words).map((part, i) =>
          i % 2 ? (
            <mark key={i} className="rounded-[2px] bg-neutral-tint font-semibold text-foreground">
              {part}
            </mark>
          ) : (
            part
          ),
        )}
      </span>
    </button>
  );
}

// api/ask.py's limits: the last 20 turns, each at most 4000 characters.
const HISTORY_TURNS = 20;
const HISTORY_CHARS = 4000;

function askError(error: Error) {
  if (error instanceof ApiError && error.code === 'MODEL_UNAVAILABLE') return `Argon couldn’t answer, so there is no answer: ${error.message}`;
  return error.message;
}

// Argon writes Markdown. Only code fences, `code` and **bold** are drawn; anything else stays as written.
function Answer({ text }: { text: string }) {
  return (
    <div className="text-sm leading-6 whitespace-pre-wrap wrap-anywhere">
      {text.split(/```\w*\n?/).map((part, i) =>
        i % 2 ? (
          <pre key={i} className="my-1 overflow-x-auto rounded-sm border bg-code px-3 py-2 font-mono leading-5">{part.trimEnd()}</pre>
        ) : (
          part.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/).map((s, j) =>
            j % 2 === 0 ? s : s[0] === '`' ? <code key={`${i}-${j}`} className="font-mono">{s.slice(1, -1)}</code> : <strong key={`${i}-${j}`} className="font-semibold">{s.slice(2, -2)}</strong>,
          )
        ),
      )}
    </div>
  );
}

function AskPane({ repoId, graph, onSelect, hidden }: { repoId: string; graph: UseQueryResult<GraphPayload>; onSelect: (id: string | null) => void; hidden: boolean }) {
  const [draft, setDraft] = useState('');
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const ask = useMutation({
    mutationFn: (question: string) => {
      const history = turns
        .flatMap(({ question: previous, answer }) => [
          { role: 'user' as const, content: previous.slice(0, HISTORY_CHARS) },
          { role: 'assistant' as const, content: answer.answer.slice(0, HISTORY_CHARS) },
        ])
        .slice(-HISTORY_TURNS);
      return askRepository(repoId, question, history).then((answer) => ({ question, answer }));
    },
    onSuccess: (turn) => {
      setTurns((current) => [...current, turn]);
      setDraft('');
    },
  });
  const submit = () => {
    const question = draft.trim();
    if (question && !ask.isPending) ask.mutate(question);
  };

  return (
    <aside aria-label="Ask about this repository" hidden={hidden} className="flex-none border-t bg-card xl:relative xl:w-[380px] xl:border-t-0 xl:border-l">
      <div className="flex flex-col xl:absolute xl:inset-0">
        <header className="flex flex-col gap-1 border-b p-4">
          <h2 className="font-medium">Ask about this code</h2>
          <p className="text-sm text-muted-foreground">Answers use repository search and cite source locations. Conversation history stays in this browser session.</p>
        </header>
        <div aria-live="polite" className="flex min-h-40 flex-col gap-4 p-4 xl:min-h-0 xl:flex-1 xl:overflow-y-auto">
          {!turns.length && <p className="text-sm text-muted-foreground">Ask a question about the repository to see the answer and its retrieval evidence.</p>}
          {turns.map((turn, index) => (
            <article key={`${index}-${turn.question}`} className="flex min-w-0 flex-col gap-2 border-b pb-4 last:border-b-0">
              <h3 className="font-medium">{turn.question}</h3>
              {!turn.answer.grounded && <p role="status" className="rounded-sm border border-warning px-2 py-1 text-sm text-warning">Not grounded in the code</p>}
              <Answer text={turn.answer.answer} />
              {turn.answer.truncated && <p role="status" className="text-sm text-warning">The answer was truncated.</p>}
              {turn.answer.citations.length > 0 && (
                <section aria-label="Citations" className="flex flex-col gap-2">
                  <h4 className="text-sm font-medium">Citations</h4>
                  {turn.answer.citations.map((citation, citationIndex) => {
                    const node = graph.data?.nodes.find((item) => item.path === citation.path || item.label === citation.path);
                    return (
                      <div key={`${citation.path}-${citation.start_line}-${citationIndex}`} className="rounded-sm border px-3 py-2">
                        <button
                          type="button"
                          disabled={!node}
                          onClick={() => node && onSelect(node.id)}
                          className="font-mono text-left text-sm underline underline-offset-4 disabled:no-underline disabled:text-muted-foreground"
                        >
                          {citation.path}
                          {citation.start_line !== null && `:${citation.start_line}${citation.end_line !== null && citation.end_line !== citation.start_line ? `–${citation.end_line}` : ''}`}
                        </button>
                        {citation.symbol && <p className="font-mono text-sm wrap-anywhere text-muted-foreground">{citation.symbol}</p>}
                        {citation.snippet && <p className="mt-1 font-mono text-sm leading-5 whitespace-pre-wrap wrap-anywhere">{citation.snippet}</p>}
                      </div>
                    );
                  })}
                </section>
              )}
              <section aria-label="Retrieval evidence" className="flex flex-col gap-1 border-t pt-2">
                <h4 className="text-sm font-medium">Retrieval</h4>
                {turn.answer.retrieval.map((item, retrievalIndex) => (
                  <p key={`${item.tool}-${retrievalIndex}`} className="break-words text-sm text-muted-foreground">
                    <span className="font-mono">{item.tool}</span>{item.query && ` · “${item.query}”`}{item.mode_used && ` · ${item.mode_used}`}
                    {item.native_hybrid !== null && ` · ${item.native_hybrid ? 'native hybrid' : 'app-side fusion'}`} · {item.hit_count} {item.hit_count === 1 ? 'hit' : 'hits'}
                  </p>
                ))}
                {!turn.answer.retrieval.length && <p className="text-sm text-muted-foreground">No retrieval calls were reported.</p>}
              </section>
            </article>
          ))}
          {ask.isPending && (
            <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <HourglassIcon size={16} aria-hidden /> Argon is searching the repository and preparing an answer. This can take up to a minute.
            </p>
          )}
          {ask.isError && <p role="alert" className="text-sm text-failed">{askError(ask.error)}</p>}
        </div>
        <form
          className="flex flex-col gap-2 border-t p-4"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label htmlFor="ask-question" className="sr-only">Ask a question about the repository</label>
          <textarea
            id="ask-question"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about this repository…"
            rows={3}
            disabled={ask.isPending}
            className="min-h-20 resize-y rounded-sm border border-input bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
          />
          <Button type="submit" disabled={!draft.trim() || ask.isPending}>{ask.isPending ? 'Working…' : 'Ask'}</Button>
        </form>
      </div>
    </aside>
  );
}

/** 09 Search: code chunks by keyword, meaning or both, each leading to its module on the graph. Template: kit.js s09. */
export default function SearchScreen() {
  const { repoId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const module = params.get('module');
  const runId = params.get('run');
  const [draft, setDraft] = useState('');
  // Searches run on Enter, not per keystroke: each vector or hybrid search embeds the query once.
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('hybrid');
  const [picked, setPicked] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const graph = useQuery({ queryKey: ['graph', repoId, runId], queryFn: () => getGraph(repoId, runId) });
  const planId = params.get('plan');
  const plan = useQuery({ queryKey: ['plan', planId], queryFn: () => getPlan(planId!), enabled: Boolean(planId) });
  const results = useQuery({
    queryKey: ['search', repoId, query, mode],
    queryFn: () => searchRepository(repoId, query, mode),
    enabled: Boolean(query),
    refetchInterval: (q) => (building(q.state.error) ? NOT_READY_POLL_MS : false),
  });
  const words = queryWords(query);

  const select = (id: string | null) =>
    setParams(
      (p) => {
        if (id) p.set('module', id);
        else p.delete('module');
        return p;
      },
      { replace: true },
    );
  const submit = () => {
    const q = draft.trim();
    if (q && q === query) void results.refetch();
    else setQuery(q);
  };

  const { data, error } = results;
  return (
    <main className="flex min-h-[480px] flex-1 flex-col xl:flex-row">
      <section aria-label="Search" className="flex-none border-b bg-card xl:relative xl:w-[500px] xl:border-r xl:border-b-0 min-[1600px]:w-[560px]">
        <div className="flex flex-col xl:absolute xl:inset-0">
          <div className="flex flex-col gap-3 border-b p-4">
            <form
              role="search"
              className="flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <label className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-sm border border-input bg-card px-2 text-sm has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring">
                <MagnifyingGlassIcon size={16} aria-hidden className="flex-none text-muted-foreground" />
                <input
                  type="search"
                  value={draft}
                  maxLength={500}
                  onChange={(event) => setDraft(event.target.value)}
                  aria-label="Search the code"
                  placeholder="Search the code"
                  className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
                />
              </label>
              <div role="group" aria-label="Search mode" className="flex h-8 flex-none overflow-hidden rounded-md border border-input">
                {MODES.map(([m, label]) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={m === mode}
                    onClick={() => setMode(m)}
                    className="border-input px-3 text-sm font-medium text-muted-foreground transition-colors not-first:border-l focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-current aria-pressed:bg-foreground aria-pressed:text-card"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </form>
            {data && (
              <div role="status" className="flex items-center gap-2 text-sm">
                {data.hits.length === 1 ? '1 result' : `${data.hits.length} results`}
                {data.mode_used === 'hybrid' ? (
                  <Tooltip>
                    <TooltipTrigger className="ml-auto inline-flex h-6 items-center gap-1 rounded-sm bg-neutral-tint px-2 whitespace-nowrap text-neutral">
                      <InfoIcon size={16} aria-hidden />
                      {data.native_hybrid ? 'Native Atlas hybrid' : 'App-side fusion'}
                    </TooltipTrigger>
                    <TooltipContent side="bottom">
                      {data.native_hybrid
                        ? 'Atlas merged the keyword and vector rankings with $rankFusion.'
                        : 'This Atlas can’t run $rankFusion, so the app merged the keyword and vector rankings.'}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  data.mode_used !== mode && (
                    <span className="ml-auto text-muted-foreground">Vector search is unavailable, so these are keyword results only.</span>
                  )
                )}
              </div>
            )}
          </div>
          <div className="xl:min-h-0 xl:flex-1 xl:overflow-y-auto">
            {!query ? (
              <p className="p-4 text-sm text-muted-foreground">
                Find code by keyword, by meaning (vector), or both (hybrid), then press Enter. Pick a result to open its module beside
                the graph.
              </p>
            ) : error instanceof ApiError && error.code === 'SEARCH_INDEX_NOT_READY' ? (
              <NotReadyNotice error={error} onKeyword={mode === 'keyword' ? undefined : () => setMode('keyword')} />
            ) : error ? (
              <p className="p-4 text-sm">Couldn’t search: {error.message}</p>
            ) : !data ? (
              <p className="p-4 text-sm text-muted-foreground">Searching…</p>
            ) : !data.hits.length ? (
              <p className="p-4 text-sm text-muted-foreground">Nothing matches “{query}”.</p>
            ) : (
              <ol>
                {data.hits.map((hit) => (
                  <li key={hit.chunk_id}>
                    <Hit
                      hit={hit}
                      words={words}
                      picked={hit.chunk_id === picked && hit.module_id === module}
                      onPick={() => {
                        setPicked(hit.chunk_id);
                        select(hit.module_id);
                      }}
                    />
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </section>
      <GraphArea graph={graph} selected={module} filter="" onSelect={select} zoomToSelected />
      {/* An open module takes the Ask pane's place. Ask stays mounted, so its conversation is back when the inspector closes. */}
      {module && graph.data && (
        <aside
          aria-label="Module inspector"
          className={cn('flex-none border-t bg-card xl:relative xl:border-t-0 xl:border-l', expanded ? 'xl:w-[560px]' : 'xl:w-[380px]')}
        >
          <div className="flex flex-col xl:absolute xl:inset-0 xl:overflow-y-auto">
            <ModuleInspector
              key={module}
              repoId={repoId}
              moduleId={module}
              graph={graph.data}
              runId={runId}
              unit={plan.data?.units.find((u) => u.module_ids.includes(module))}
              expanded={expanded}
              onExpand={setExpanded}
              onClose={() => select(null)}
              onSelect={select}
            />
          </div>
        </aside>
      )}
      <AskPane repoId={repoId} graph={graph} onSelect={select} hidden={Boolean(module && graph.data)} />
    </main>
  );
}
