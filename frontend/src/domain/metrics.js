export const MAX_METRIC_VALUE = 2147483647;
export const METRICS = [
  { field: 'online_drivers', label: 'Online Drivers', description: 'Drivers currently available online.' },
  { field: 'ride_requests', label: 'Ride Requests', description: 'Total requests in this operational snapshot.' },
  { field: 'accepted_requests', label: 'Accepted Requests', description: 'Requests accepted by a driver.' },
  { field: 'cancelled_requests', label: 'Cancelled Requests', description: 'Requests that have been cancelled.' },
  { field: 'waiting_drivers', label: 'Drivers Waiting', description: 'Online drivers waiting in this zone.' },
];

export function zeroMetrics() {
  return Object.fromEntries(METRICS.map(({ field }) => [field, 0]));
}

export function validateMetrics(values) {
  const errors = {};
  for (const { field } of METRICS) {
    if (!Number.isInteger(values[field]) || values[field] < 0 || values[field] > MAX_METRIC_VALUE) {
      errors[field] = 'Enter a whole number between 0 and 2,147,483,647.';
    }
  }
  if (!errors.accepted_requests && !errors.cancelled_requests && !errors.ride_requests &&
      values.accepted_requests + values.cancelled_requests > values.ride_requests) {
    errors.accepted_requests = 'Accepted and cancelled requests must not exceed ride requests.';
    errors.cancelled_requests = errors.accepted_requests;
  }
  if (!errors.waiting_drivers && !errors.online_drivers && values.waiting_drivers > values.online_drivers) {
    errors.waiting_drivers = 'Waiting drivers must not exceed online drivers.';
  }
  return errors;
}
