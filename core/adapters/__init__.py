"""Python adapters for kits that do not speak the evaluator contract
themselves.
Each adapter kit is declared in core/kit_registry.py; the declaration's
`factory` string ("module.path:Name", relative to core/) names the class
that contract.load_factory imports when the kit opens."""
