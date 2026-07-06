# PyInstaller runtime hook — pkg_resources stub
#
# setuptools 82+ removed pkg_resources from the wheel; pyfilesystem2 / pyfatfs
# call pkg_resources.declare_namespace() at import time.  This hook runs before
# any user code so the import never fails inside the frozen app.
import sys

if "pkg_resources" not in sys.modules:
    try:
        import pkg_resources  # noqa: F401  (setuptools still present)
    except ImportError:
        import types

        _stub = types.ModuleType("pkg_resources")

        def _declare_namespace(name: str) -> None:
            pass

        _stub.declare_namespace = _declare_namespace  # type: ignore[attr-defined]
        sys.modules["pkg_resources"] = _stub
