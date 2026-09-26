"""Python adapters for kits that do not speak the evaluator contract
themselves (Phase C1 spec, docs/superpowers/specs/2026-09-25-prodtools-kit-design.md).
register_all is idempotent; core/contract.py calls it before it looks a
kit up."""


def register_all(register, adapters) -> None:
    """Register every adapter this package holds that `adapters` lacks."""
