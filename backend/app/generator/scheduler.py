"""100 ms event budgets; no unbounded catch-up bursts under backpressure."""
from .actions import choose_action, connect_driver, execute_action
from .entities import DriverState
from .events import OperationEvent
from .simulation import Simulation


class EventBudgetScheduler:
    tick_seconds = 0.1

    def __init__(self, target_events_per_second: int, driver_count: int):
        if type(target_events_per_second) is not int or target_events_per_second <= 0:
            raise ValueError('target_events_per_second must be a positive integer')
        self.target = target_events_per_second
        self._credit_tenths = 0
        # Connect 10% of the pool (at least one) before allowing ride actions.
        self.warmup_drivers = max(1, (driver_count + 9) // 10)
        self.warmed_up = False

    def next_batch(self, sim: Simulation) -> list[OperationEvent]:
        self._credit_tenths = min(self._credit_tenths + self.target,
                                  max(20, self.target + 10))
        events = []
        while self._credit_tenths >= 10:
            budget = self._credit_tenths // 10
            if not self.warmed_up:
                if budget < 2:
                    break
                emitted = connect_driver(sim)
                if len(sim.driver_pools[DriverState.WAITING]) >= self.warmup_drivers:
                    self.warmed_up = True
            else:
                action = choose_action(sim, event_budget=budget)
                if action is None:
                    break
                emitted = execute_action(sim, action)
            if not emitted:
                break
            self._credit_tenths -= len(emitted) * 10
            events.extend(emitted)
        return events
