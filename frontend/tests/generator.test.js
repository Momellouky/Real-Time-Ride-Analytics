import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useGeneratorStore } from '../src/stores/generator.js';
import { generatorErrors, generatorInput, positiveInteger, validateGeneratorStatus } from '../src/domain/generator.js';
import { getGeneratorStatus, startGenerator, stopGenerator } from '../src/services/api.js';

vi.mock('../src/services/api.js', () => ({ getGeneratorStatus: vi.fn(), startGenerator: vi.fn(), stopGenerator: vi.fn() }));

const idle = { simulation_id: null, status: 'STOPPED', target_events_per_second: 0,
  actual_events_per_second: 0, generated_events: 0, published_events: 0, user_pool_size: 0,
  driver_pool_size: 0, in_memory: { idle_users: 0, waiting_users: 0, users_in_ride: 0,
    offline_drivers: 0, waiting_drivers: 0, assigned_drivers: 0 }, last_error: null };
const running = { ...idle, status: 'RUNNING', simulation_id: 'sim-test', target_events_per_second: 250,
  user_pool_size: 10000, driver_pool_size: 2000, generated_events: 10, published_events: 10 };

beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); setActivePinia(createPinia()); getGeneratorStatus.mockResolvedValue(idle); });
afterEach(() => { useGeneratorStore().unwatch(); vi.useRealTimers(); });

it.each(['', ' ', '-1', '1.5', '1e3', null, undefined, true, 0, -1, 0.5, Number.MAX_SAFE_INTEGER + 1])(
  'rejects invalid whole-number input %s', (value) => expect(positiveInteger(value)).toBeNull());
it.each([1, '100', 250, 1250])('accepts positive whole-number input %s', (value) => expect(positiveInteger(value)).toBe(Number(value)));
it('validates custom input and converts the complete payload', () => {
  expect(generatorInput({ user_count: '10', driver_count: '2', rate: 'custom', custom_rate: '1250' }))
    .toEqual({ user_count: 10, driver_count: 2, target_events_per_second: 1250 });
  expect(Object.keys(generatorErrors({ user_count: '', driver_count: -1, rate: 'custom', custom_rate: '' }))).toHaveLength(3);
});
it.each([null, {}, { ...idle, status: 'UNKNOWN' }, { ...idle, published_events: 1 },
  { ...running, simulation_id: null }, { ...idle, actual_events_per_second: Infinity },
  { ...idle, in_memory: {} }])('rejects malformed status', (data) => expect(() => validateGeneratorStatus(data)).toThrow(/invalid generator status/));

it('polls once per second and stops on navigation without stopping the run', async () => {
  const store = useGeneratorStore();
  store.watch();
  await vi.advanceTimersByTimeAsync(0);
  expect(store.canStart).toBe(true);
  expect(store.canStop).toBe(false);
  await vi.advanceTimersByTimeAsync(2000);
  expect(getGeneratorStatus).toHaveBeenCalledTimes(3);
  store.unwatch();
  await vi.advanceTimersByTimeAsync(5000);
  expect(getGeneratorStatus).toHaveBeenCalledTimes(3);
  expect(stopGenerator).not.toHaveBeenCalled();
});

it('prevents overlapping slow polls, aborts them, and ignores late data', async () => {
  let resolve;
  getGeneratorStatus.mockReturnValue(new Promise((r) => { resolve = r; }));
  const store = useGeneratorStore();
  store.watch();
  await vi.advanceTimersByTimeAsync(5000);
  expect(getGeneratorStatus).toHaveBeenCalledOnce();
  const signal = getGeneratorStatus.mock.calls[0][0];
  store.unwatch();
  expect(signal.aborted).toBe(true);
  resolve(running);
  await vi.advanceTimersByTimeAsync(0);
  expect(store.current).toBeNull();
});

it('keeps diagnostics on polling failure, blocks Start, and recovers', async () => {
  getGeneratorStatus.mockResolvedValueOnce(idle).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(idle);
  const store = useGeneratorStore();
  store.watch();
  await vi.advanceTimersByTimeAsync(1000);
  expect(store.current).toEqual(idle);
  expect(store.statusError).toBe('offline');
  expect(store.canStart).toBe(false);
  await vi.advanceTimersByTimeAsync(1000);
  expect(store.canStart).toBe(true);
});

it('sends custom configuration, prevents duplicate controls, and retains final stats', async () => {
  const store = useGeneratorStore();
  await store.refresh();
  store.draft.rate = 'custom'; store.draft.custom_rate = '1250';
  expect(store.highRate).toBe(true);
  expect(store.canStart).toBe(true);
  let resolve;
  startGenerator.mockReturnValue(new Promise((r) => { resolve = r; }));
  const starting = store.start();
  expect(store.pending).toBe('start');
  await store.start();
  expect(startGenerator).toHaveBeenCalledOnce();
  expect(startGenerator).toHaveBeenCalledWith({ user_count: 10000, driver_count: 2000, target_events_per_second: 1250 });
  getGeneratorStatus.mockResolvedValue(running);
  resolve(running); await starting;
  expect(store.canStart).toBe(false); expect(store.canStop).toBe(true); expect(store.canEdit).toBe(false);
  const stopped = { ...running, status: 'STOPPED' };
  stopGenerator.mockResolvedValue(stopped); getGeneratorStatus.mockResolvedValue(stopped);
  await store.stop();
  expect(store.current.generated_events).toBe(10);
  expect(store.feedback).toContain('statistics are retained');
  expect(store.canStart).toBe(true); expect(store.canStop).toBe(false);
});

it('invalid configuration never sends Start', async () => {
  const store = useGeneratorStore(); await store.refresh();
  store.draft.user_count = ''; await store.start();
  expect(startGenerator).not.toHaveBeenCalled();
});

it('reconciles a failed Start without claiming the generator is stopped', async () => {
  const store = useGeneratorStore(); await store.refresh();
  startGenerator.mockRejectedValue(new Error('request timed out'));
  getGeneratorStatus.mockResolvedValue(running);
  await store.start();
  expect(store.commandError).toContain('request timed out');
  expect(store.current.status).toBe('RUNNING');
  expect(store.canStart).toBe(false); expect(store.canStop).toBe(true);
});

it('does not let an old poll overwrite the command response', async () => {
  const store = useGeneratorStore(); await store.refresh();
  let resolveOld;
  getGeneratorStatus.mockReturnValueOnce(new Promise((r) => { resolveOld = r; })).mockResolvedValue(running);
  const oldPoll = store.refresh();
  startGenerator.mockResolvedValue(running);
  await store.start();
  resolveOld(idle); await oldPoll;
  expect(store.current.status).toBe('RUNNING');
});

it('adopts an existing run config, blocks stopping during STOPPING, and exposes ERROR', async () => {
  getGeneratorStatus.mockResolvedValue({ ...running, target_events_per_second: 1250, user_pool_size: 42, status: 'STOPPING' });
  const store = useGeneratorStore(); await store.refresh();
  expect(store.draft.user_count).toBe(42); expect(store.draft.rate).toBe('custom');
  expect(store.draft.custom_rate).toBe(1250);
  expect(store.canStart).toBe(false); expect(store.canStop).toBe(false);
  getGeneratorStatus.mockResolvedValue({ ...running, status: 'ERROR', last_error: 'drain failed' });
  await store.refresh(); expect(store.current.last_error).toBe('drain failed'); expect(store.canStart).toBe(true);
});
