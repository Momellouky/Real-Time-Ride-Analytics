export const CARDS = [
  ['total_users', 'Total user pool', 'Configured population'],
  ['active_users', 'Active users', 'Waiting for a driver or in a ride'],
  ['online_drivers', 'Online drivers', 'Connected, waiting or assigned'],
  ['waiting_drivers', 'Waiting drivers', 'Available for assignment'],
  ['ride_requests', 'Ride requests', 'Last 60 seconds'],
  ['accepted_rides', 'Accepted rides', 'Last 60 seconds'],
  ['cancelled_rides', 'Cancelled rides', 'Last 60 seconds'],
  ['completed_rides', 'Completed rides', 'Last 60 seconds'],
];
const integer = (value) => Number.isSafeInteger(value) && value >= 0;
export function validateDashboardV2(data) {
  const fail = () => { throw new Error('The service returned invalid event analytics. Please retry.'); };
  if (!data || !integer(data.as_of_ms) || !['STOPPED', 'WARMING_UP', 'RUNNING', 'STOPPING', 'ERROR'].includes(data.generator_status)) fail();
  if (data.run !== null && (!data.run || typeof data.run.simulation_id !== 'string' || !data.run.simulation_id ||
    !['user_pool_size', 'driver_pool_size', 'target_events_per_second', 'started_at'].every((f) => integer(data.run[f])))) fail();
  if (!CARDS.every(([f]) => integer(data.metrics?.[f])) || !integer(data.observed_users)) fail();
  if (!['connected', 'waiting', 'assigned', 'offline'].every((f) => integer(data.driver_states?.[f]))) fail();
  for (const [field, width, duration, values] of [
    ['ride_history', 60000, 3600000, ['requested', 'accepted', 'cancelled', 'completed']],
    ['event_rate', 10000, 600000, ['event_count']],
  ]) {
    if (!Array.isArray(data[field])) fail();
    let previous = -1;
    for (const row of data[field]) {
      if (!integer(row.time_bucket) || row.time_bucket <= previous || row.time_bucket % width ||
        row.time_bucket < Math.floor((data.as_of_ms - duration) / width) * width || row.time_bucket > data.as_of_ms ||
        !values.every((f) => integer(row[f]))) fail();
      if (field === 'event_rate' && (!Number.isFinite(row.events_per_second) || Math.abs(row.events_per_second - row.event_count / 10) > 1e-8)) fail();
      previous = row.time_bucket;
    }
  }
  const states = data.driver_states;
  if (states.connected + states.waiting + states.assigned !== data.metrics.online_drivers ||
    states.waiting !== data.metrics.waiting_drivers) fail();
  if (data.run && (data.metrics.total_users !== data.run.user_pool_size ||
    data.metrics.active_users > data.run.user_pool_size || data.observed_users > data.run.user_pool_size ||
    states.connected + states.waiting + states.assigned + states.offline !== data.run.driver_pool_size)) fail();
  return data;
}
