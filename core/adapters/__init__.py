"""Python adapters for kits that do not speak the evaluator contract
themselves (Phase C1 spec, docs/superpowers/specs/2026-09-25-prodtools-kit-design.md).
Each adapter kit is declared in core/kit_registry.py; the declaration's
`factory` string ("module.path:Name", relative to core/) names the class
that contract.load_factory imports when the kit opens."""
