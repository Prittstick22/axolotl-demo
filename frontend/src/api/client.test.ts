import { afterEach, describe, expect, it, vi } from 'vitest';

import { API_BASE, ApiError, apiFetch, approvePlan, artefactUrl, askRepository, downloadFile } from './client';

const reply = (body: string, init: ResponseInit) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, init)));
};

afterEach(() => vi.unstubAllGlobals());

describe('apiFetch', () => {
  it('turns the error envelope into an ApiError', async () => {
    reply(JSON.stringify({ error: { code: 'PLAN_NOT_APPROVED', message: 'Approve first', details: { a: 1 } } }), {
      status: 409,
    });
    await expect(apiFetch('/x')).rejects.toMatchObject({ code: 'PLAN_NOT_APPROVED', status: 409, details: { a: 1 } });
  });

  it('turns a non-JSON error page into an HTTP_ERROR with the status', async () => {
    reply('<html>502 Bad Gateway</html>', { status: 502, statusText: 'Bad Gateway' });
    const error = await apiFetch('/x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'HTTP_ERROR', status: 502, message: '502 Bad Gateway' });
  });

  it('turns a non-JSON success body into an HTTP_ERROR, not a SyntaxError', async () => {
    reply('<html>captive portal</html>', { status: 200 });
    const error = await apiFetch('/x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'HTTP_ERROR', status: 200 });
  });

  it('still returns parsed JSON, and null for an empty body', async () => {
    reply('{"status":"ok"}', { status: 200 });
    await expect(apiFetch('/x')).resolves.toEqual({ status: 'ok' });
    reply('', { status: 200 });
    await expect(apiFetch('/x')).resolves.toBeNull();
  });

  it('lets an abort through instead of calling it an outage', async () => {
    const controller = new AbortController();
    const abort = new DOMException('Aborted', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => {
      controller.abort();
      return Promise.reject(abort);
    }));
    await expect(askRepository('r', 'q', [], controller.signal)).rejects.toBe(abort);
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});

describe('approvePlan', () => {
  it.each([true, false])('sends approved: %s', async (approved) => {
    reply('{}', { status: 200 });
    await approvePlan('plan_1', approved);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(`${API_BASE}/plans/plan_1/approve`);
    expect(JSON.parse(String(init?.body))).toEqual({ approved });
  });
});

describe('artefactUrl', () => {
  it('resolves the download path against the API origin, not API_BASE', () => {
    const url = artefactUrl({ artefact_id: 'a', kind: 'patch', sha256: '', download_url: '/api/v1/artefacts/a/download' });
    expect(url).toBe(`${new URL(API_BASE).origin}/api/v1/artefacts/a/download`);
  });
});

describe('downloadFile', () => {
  it('throws the server’s error instead of saving an error page', async () => {
    reply(JSON.stringify({ error: { code: 'ARTEFACT_NOT_FOUND', message: 'Gone', details: {} } }), { status: 404 });
    await expect(downloadFile('http://x/a', 'a.patch')).rejects.toMatchObject({ code: 'ARTEFACT_NOT_FOUND', status: 404 });
  });
});
