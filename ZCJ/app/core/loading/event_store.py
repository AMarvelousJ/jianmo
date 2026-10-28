from __future__ import annotations

from collections import defaultdict

from app.models.loading import LoadingEvent


class LoadingEventStore:
    def __init__(self, max_events_per_task: int = 2000) -> None:
        self.max_events_per_task = max_events_per_task
        self._events: dict[str, list[LoadingEvent]] = defaultdict(list)
        self._next_id = 1

    def append(self, event: LoadingEvent) -> LoadingEvent:
        event = event.model_copy(update={"event_id": self._next_id}, deep=True)
        self._next_id += 1
        events = self._events[event.task_id]
        events.append(event)
        if len(events) > self.max_events_per_task:
            del events[: len(events) - self.max_events_per_task]
        return event

    def list(
        self,
        task_id: str,
        *,
        event_type: str | None = None,
        round_no: int | None = None,
        batch_no: int | None = None,
    ) -> list[LoadingEvent]:
        result = list(self._events.get(task_id, []))
        if event_type is not None:
            result = [event for event in result if event.event_type == event_type]
        if round_no is not None:
            result = [event for event in result if event.round_no == round_no]
        if batch_no is not None:
            result = [event for event in result if event.batch_no == batch_no]
        return [event.model_copy(deep=True) for event in result]

    def delete(self, task_id: str) -> None:
        self._events.pop(task_id, None)
