// One place that knows where the API lives, so the deploy target is a build
// variable rather than something sprinkled through components.
const BASE = import.meta.env.VITE_API_BASE || '';

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // Not JSON. The status line is the best we have.
    }
    throw new Error(detail);
  }
  return res.json();
}

export const getDecision = (day) => get(`/api/decision/${day}`);
export const getAccuracy = () => get('/api/accuracy');
export const getLeadTime = () => get('/api/lead-time');
export const getHealth = () => get('/api/health');
