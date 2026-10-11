export const RATE_PRESETS = [50, 100, 250, 500, 1000];
export const ACTIVE_STATES = ['WARMING_UP', 'RUNNING', 'STOPPING'];
export const COUNT_FIELDS = ['idle_users', 'waiting_users', 'users_in_ride',
  'offline_drivers', 'waiting_drivers', 'assigned_drivers'];

export function positiveInteger(value) {
  if (typeof value === 'string' && !/^\d+$/.test(value)) return null;
  if (!['string', 'number'].includes(typeof value)) return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : null;
}

export function generatorInput(draft) {
  return { user_count: positiveInteger(draft.user_count), driver_count: positiveInteger(draft.driver_count),
    target_events_per_second: positiveInteger(draft.rate === 'custom' ? draft.custom_rate : draft.rate) };
}

export function generatorErrors(draft) {
  return Object.fromEntries(Object.entries(generatorInput(draft))
    .filter(([, value]) => value === null).map(([key]) => [key, 'Enter a positive whole number.']));
}

export function validateGeneratorStatus(data) {
  const nonnegative = (value) => Number.isSafeInteger(value) && value >= 0;
  if (!data || !['STOPPED', 'ERROR', ...ACTIVE_STATES].includes(data.status) ||
      !(data.simulation_id === null || (typeof data.simulation_id === 'string' && data.simulation_id.length > 0)) ||
      !['target_events_per_second', 'generated_events', 'published_events', 'user_pool_size', 'driver_pool_size']
        .every((field) => nonnegative(data[field])) ||
      !Number.isFinite(data.actual_events_per_second) || data.actual_events_per_second < 0 ||
      !COUNT_FIELDS.every((field) => nonnegative(data.in_memory?.[field])) ||
      !(data.last_error === null || typeof data.last_error === 'string') ||
      data.published_events > data.generated_events ||
      (ACTIVE_STATES.includes(data.status) && (!data.simulation_id || !data.target_events_per_second))) {
    throw new Error('The service returned invalid generator status. Retry to refresh it.');
  }
  return data;
}
