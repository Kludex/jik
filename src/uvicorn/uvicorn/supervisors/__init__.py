from uvicorn.supervisors.multiprocess import Multiprocess

try:
    from uvicorn.supervisors.watchgodreload import WatchGodReload as ChangeReload
except ImportError:  # pragma: no cover
    from uvicorn.supervisors.statreload import StatReload as ChangeReload

__all__ = ["Multiprocess", "ChangeReload"]
