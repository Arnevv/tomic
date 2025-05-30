"""Wrapper script to launch the journal inspector CLI."""

from tomic.journal import journal_inspector

if __name__ == "__main__":
    # The CLI entrypoint was renamed to ``main`` in ``tomic.journal.journal_inspector``.
    # Keep this lightweight wrapper functional by calling the new function.
    journal_inspector.main()
