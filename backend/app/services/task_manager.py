from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock

from app.core.config import get_settings
from app.services.indexing import get_indexing_service


class TaskManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=get_settings().index_worker_count)
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit_index(self, document_id: str) -> bool:
        with self._lock:
            current = self._futures.get(document_id)
            if current and not current.done():
                return False
            future = self._executor.submit(get_indexing_service().index_document, document_id)
            self._futures[document_id] = future
            return True

    def is_running(self, document_id: str) -> bool:
        with self._lock:
            future = self._futures.get(document_id)
            return bool(future and not future.done())


_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager

