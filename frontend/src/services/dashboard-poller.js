// A single request at a time; stop cancels pending work and ignores late results.
export function createDashboardPoller({ request, onData, onError, onRefreshing, interval }) {
  let timer = null;
  let active = false;
  let controller = null;
  let inFlight = false;
  let generation = 0;

  async function refresh() {
    if (!active || inFlight) return;
    const session = generation;
    inFlight = true;
    controller = new AbortController();
    onRefreshing(true);
    try {
      const payload = await request(controller.signal);
      if (active && generation === session) onData(payload);
    } catch (error) {
      if (active && generation === session) onError(error);
    } finally {
      inFlight = false;
      if (active && generation === session) onRefreshing(false);
    }
  }

  function start() {
    if (active) return;
    active = true;
    generation++;
    timer = setInterval(refresh, interval);
    void refresh();
  }

  function stop() {
    active = false;
    generation++;
    clearInterval(timer);
    timer = null;
    controller?.abort();
    onRefreshing(false);
  }

  return { start, stop, refresh };
}
