import { describe, expect, it } from 'vitest';

import { scopedSearch } from './utils';

describe('scopedSearch', () => {
  it('keeps the run and plan, drops a screen’s own params', () => {
    expect(scopedSearch(new URLSearchParams('plan=p1&run=r1&module=m&unit=u&path=a.py'))).toBe('?plan=p1&run=r1');
  });

  it('is empty when there is nothing to carry', () => {
    expect(scopedSearch(new URLSearchParams('module=m'))).toBe('');
  });

  it.each(['module', 'unit', 'path'])('drops ?%s on its own', (key) => {
    expect(scopedSearch(new URLSearchParams(`run=r1&${key}=x`))).toBe('?run=r1');
  });

  it('adds the param a link sets for its target, replacing the screen’s own', () => {
    expect(scopedSearch(new URLSearchParams('run=r1&module=old&path=a.py'), { module: 'new' })).toBe('?run=r1&module=new');
    expect(scopedSearch(new URLSearchParams(''), { unit: 'u 1' })).toBe('?unit=u+1');
  });
});
