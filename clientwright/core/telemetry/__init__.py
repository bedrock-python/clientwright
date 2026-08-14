"""Single telemetry implementation for the whole library.

Adapters never write a metric or a log line: they call ``send`` and the engine
drives the one ``ClientTelemetry`` emitter, so the schema physically cannot
diverge between backends.
"""
