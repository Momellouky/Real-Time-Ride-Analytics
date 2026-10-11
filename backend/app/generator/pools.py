"""Dense indexed sets: constant-time random selection, insertion, and removal."""
from collections.abc import Iterable, Iterator
from random import Random


class StatePool:
    def __init__(self, values: Iterable[str] = ()):
        self._values: list[str] = []
        self._positions: dict[str, int] = {}
        for value in values:
            self.add(value)

    def __len__(self) -> int:
        return len(self._values)

    def __contains__(self, value: str) -> bool:
        return value in self._positions

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def add(self, value: str) -> None:
        if value in self._positions:
            raise ValueError(f'{value} already belongs to pool')
        self._positions[value] = len(self._values)
        self._values.append(value)

    def remove(self, value: str) -> None:
        position = self._positions.pop(value)
        last = self._values.pop()
        if position < len(self._values):
            self._values[position] = last
            self._positions[last] = position

    def choose(self, rng: Random) -> str | None:
        return rng.choice(self._values) if self._values else None

    def check_invariants(self) -> None:
        assert len(self._values) == len(self._positions), 'Pool index size mismatch'
        assert all(self._positions.get(value) == index
                   for index, value in enumerate(self._values)), 'Pool index mismatch'
