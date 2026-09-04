"""Real PostgreSQL concurrency for ``Message.sequence`` (Phase 16 Checkpoint
2 Part B, section 5): the ordering tie-breaker column is assigned by the
database itself (``nextval()`` via ``db_default``, see
``conversations/models.py`` and migration ``0003``), never computed in
application code (no ``MAX(sequence) + 1``, which would recreate the exact
race this column exists to close) — this proves that path directly, real
threads inserting concurrently, mirroring the established pattern in
``agents/tests/test_concurrency.py``.
"""

from __future__ import annotations

import threading

import django.db as django_db
import pytest

from conversations.models import Message

from .factories import ConversationFactory, MessageFactory

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_inserts_never_duplicate_or_lose_a_sequence():
    conversation = ConversationFactory()
    n = 20
    barrier = threading.Barrier(n)
    created_ids: list[object] = [None] * n

    def make_worker(index):
        def worker():
            django_db.close_old_connections()
            barrier.wait()
            message = MessageFactory(conversation=conversation, body=f"concurrent-{index}")
            created_ids[index] = message.id
            django_db.close_old_connections()

        return worker

    threads = [threading.Thread(target=make_worker(i)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert all(created_ids), "every concurrent insert must have succeeded"
    sequences = list(Message.objects.filter(id__in=created_ids).values_list("sequence", flat=True))
    assert len(sequences) == n
    # No duplicate sequence (section 5): a real PostgreSQL sequence never
    # hands the same value to two callers, even under real concurrent
    # ``nextval()`` calls with no application-level lock involved.
    assert len(set(sequences)) == n
    # No lost assignment either: the sequence is otherwise untouched during
    # this test (module-scoped, no other writer), so these ``n`` calls
    # produced ``n`` *consecutive* values — none silently skipped.
    ordered = sorted(sequences)
    assert ordered[-1] - ordered[0] + 1 == n


def test_concurrent_inserts_preserve_deterministic_ordering_with_more_than_context_limit():
    """Combines the concurrency proof with the ordering semantics check
    (section 6): after real concurrent inserts, ``(created_at, sequence)``
    ordering must still be a well-formed, complete, duplicate-free total
    order over every row — even when more rows exist than a context window
    would ever retain.

    Note what this does *not* assert: that ``sequence`` values come out
    globally sorted by this ordering. They need not — ``sequence`` is a
    tie-breaker for messages sharing the exact same ``created_at``, not a
    global proxy for ``created_at`` itself. Under genuine thread
    interleaving, a message whose ``nextval()`` fired first can easily earn
    a *later* ``created_at`` than one that inserted after it (timestamped in
    Python before the row is written, independent of when the DB assigned
    its sequence) — ``(created_at, sequence)`` ordering correctly reflects
    that, and a global "sequence is monotonic across different timestamps"
    assertion would be testing a guarantee this design was never meant to
    provide. The genuine tie-break guarantee (identical ``created_at``
    resolved by ``sequence``) is proven deterministically, without relying
    on rare real-clock collisions, by
    ``agents/tests/test_context.py``'s
    ``test_newest_history_is_retained_even_when_created_at_ties`` and
    ``channel_ingress/tests/test_webchat.py``'s
    ``test_after_cursor_ties_are_broken_by_sequence_not_random_id``.
    """
    conversation = ConversationFactory()
    n = 15
    barrier = threading.Barrier(n)

    def make_worker(index):
        def worker():
            django_db.close_old_connections()
            barrier.wait()
            MessageFactory(conversation=conversation, body=f"row-{index}")
            django_db.close_old_connections()

        return worker

    threads = [threading.Thread(target=make_worker(i)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    ordered = list(conversation.messages.order_by("created_at", "sequence"))
    assert len(ordered) == n
    sequence_ids = [m.id for m in ordered]
    assert len(set(sequence_ids)) == n  # every row present exactly once

    # Within any genuine created_at tie-group, sequence must be strictly
    # increasing in this ordering — the one guarantee the column actually
    # makes.
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if earlier.created_at == later.created_at:
            assert earlier.sequence < later.sequence
