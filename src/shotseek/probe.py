"""Deadline boundaries for filesystem checks that the OS may not interrupt."""
import queue
import threading


def bounded_call(call, timeout):
    answers = queue.Queue(maxsize=1)
    def work():
        try:
            answers.put((True, call()))
        except Exception as exc:
            answers.put((False, exc))
    threading.Thread(target=work, daemon=True).start()
    try:
        ok, value = answers.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError("Local check exceeded its time limit") from None
    if not ok:
        raise value
    return value


def bounded_probe(call, timeout=10):
    try:
        return True, bounded_call(call, timeout)
    except Exception:
        return False, None
