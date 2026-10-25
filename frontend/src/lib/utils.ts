export { cn } from "cn"

/**
 * The query string a link to another tab carries: only the run and plan, never a screen's own ?module=, ?unit= or ?path=,
 * plus any of those the link sets for its target.
 */
export function scopedSearch(params: URLSearchParams, extra: Record<string, string> = {}): string {
  const kept = new URLSearchParams([...params].filter(([key]) => key === 'plan' || key === 'run'))
  for (const [key, value] of Object.entries(extra)) kept.set(key, value)
  return kept.size ? `?${kept}` : ''
}
