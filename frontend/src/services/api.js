const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

function errorMessage(body, fallback) {
  if (typeof body?.detail === 'string') return body.detail;
  if (Array.isArray(body?.detail)) {
    return body.detail.map(({ loc, msg }) => {
      const field = loc?.filter((part) => part !== 'body').join(' ');
      return field ? `${field.replaceAll('_', ' ')}: ${msg}` : msg;
    }).join(' ');
  }
  return fallback;
}

async function request(path, options = {}) {
  const { timeout = 15000, ...fetchOptions } = options;
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions, signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(timeout)])
        : AbortSignal.timeout(timeout),
    });
  } catch {
    throw new Error('Unable to reach the service. Check your connection and try again.');
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error('The service returned an unreadable response. Please try again.');
  }
  if (!response.ok) throw new Error(errorMessage(body, 'Unable to complete the request. Please try again.'));
  return body;
}

export const getCurrentMetrics = () => request('/api/metrics/current?zone_id=ZONE_1');
export const getDashboard = (signal) => request('/api/dashboard?zone_id=ZONE_1&window=1h', { signal });
export const updateMetrics = (payload) => request('/api/metrics', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
});

export const getGeneratorStatus = (signal) => request('/api/v2/generator/status', { signal });
export const startGenerator = (payload) => request('/api/v2/generator/start', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload), timeout: 30000,
});
export const stopGenerator = () => request('/api/v2/generator/stop', { method: 'POST', timeout: 30000 });
