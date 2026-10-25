import { ListChecksIcon, MoonIcon, SunIcon } from '@phosphor-icons/react';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { getRepository } from '@/api/client';
import { SystemChips } from '@/components/SystemChips';
import { Button } from '@/components/ui/button';
import { useRun } from '@/lib/run';
import { scopedSearch } from '@/lib/utils';
import type { SystemStatus } from '@/types/contracts';

function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  const toggle = () => {
    document.documentElement.classList.toggle('dark', !dark);
    try {
      localStorage.setItem('theme', dark ? 'light' : 'dark');
    } catch {
      // Storage blocked: the choice lasts until reload, then the system theme applies.
    }
    setDark(!dark);
  };
  return (
    <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? 'Use light theme' : 'Use dark theme'}>
      {dark ? <SunIcon size={20} aria-hidden /> : <MoonIcon size={20} aria-hidden />}
    </Button>
  );
}

/** Product name, the open repository, system status chips. Template: docs/design, "appbar". */
export function AppBar({ repoId, status }: { repoId?: string; status?: SystemStatus }) {
  const repo = useQuery({
    queryKey: ['repository', repoId],
    queryFn: () => getRepository(repoId!),
    enabled: Boolean(repoId),
  });
  const [params] = useSearchParams();
  const run = useRun(params.get('run'));

  return (
    <header className="flex min-h-14 flex-none flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b bg-card px-4 py-2">
      <div className="flex items-center gap-3">
        <Link to="/" className="font-medium">
          Axolotl
        </Link>
        {repoId && (
          <>
            <span className="h-6 w-px bg-border" aria-hidden />
            <Link
              to={{ pathname: `/repos/${encodeURIComponent(repoId)}`, search: scopedSearch(params) }}
              className="font-mono text-sm font-medium hover:underline hover:underline-offset-4"
            >
              {repo.data?.name ?? repoId}
            </Link>
          </>
        )}
      </div>
      <div className="flex items-center gap-6">
        {repoId && run.data && (
          <span className="flex items-center gap-2 font-medium">
            <ListChecksIcon size={20} aria-hidden />
            {run.data.units_verified} of {run.data.units_total} units verified
          </span>
        )}
        <div className="flex items-center gap-3">
          {status && <SystemChips status={status} />}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
