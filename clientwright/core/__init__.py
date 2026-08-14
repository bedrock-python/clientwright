"""Pure kernel of clientwright.

Everything under ``clientwright.core`` depends on the standard library only.
Deleting ``clientwright/adapters`` must leave this package importable and its
tests green; CI enforces the rule with import-linter contracts.
"""
