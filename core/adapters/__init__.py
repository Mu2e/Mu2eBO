"""Python adapters for kits that do not speak the evaluator contract
themselves (Phase C1 spec, docs/superpowers/specs/2026-09-25-prodtools-kit-design.md).
register_all is idempotent; core/contract.py calls it before it looks a
kit up."""


def register_all(register, adapters) -> None:
    """Register every adapter this package holds that `adapters` lacks."""
    if __package__ == "core.adapters":
        from core.adapters.anakit import AnakitKit
        from core.adapters.offline_preflight import OfflinePreflightKit
        from core.adapters.prodtools import ProdtoolsKit
    else:
        from adapters.anakit import AnakitKit
        from adapters.offline_preflight import OfflinePreflightKit
        from adapters.prodtools import ProdtoolsKit
    for name, factory in (("prodtools", ProdtoolsKit),
                          ("offline_preflight", OfflinePreflightKit),
                          ("anakit", AnakitKit)):
        if name not in adapters:
            register(name, factory)
