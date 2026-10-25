import type { VariantProps } from 'class-variance-authority';

import { Button, type buttonVariants } from '@/components/ui/button';

/** The "Try again" every error state offers: refetches the query that failed. */
export function RetryButton({ query, variant = 'outline' }: {
  query: { refetch: () => Promise<unknown>; isFetching: boolean };
  variant?: VariantProps<typeof buttonVariants>['variant'];
}) {
  return (
    <Button variant={variant} onClick={() => void query.refetch()} disabled={query.isFetching}>
      {query.isFetching ? 'Trying…' : 'Try again'}
    </Button>
  );
}
