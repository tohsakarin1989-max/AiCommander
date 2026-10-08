"""Exact encoder-input reuse, private to authorized rebuilds/background workers.

Only a text hash and vector are durable. Revision IDs, offsets, fragment identity
and authorization always come from the new source, never from this side table.
Preparing vectors is read-only; publish writes in the caller's transaction.
"""
import json
import re

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models.case_history_index import CaseHistoryVectorReuse
from app.services.case_semantic_evidence import text_hash
from app.services.local_embedding_service import LocalEmbeddingError, normalized_vector


def encoder_identity(embedder):
    return (embedder.state, embedder.model_version, getattr(embedder, 'dimension', None),
            getattr(embedder, 'encoder_fingerprint', None))


class FragmentVectorReuse:
    def __init__(self, db, embedder):
        self.db, self.embedder = db, embedder
        self.identity = encoder_identity(embedder)
        self.dimension = getattr(embedder, 'dimension', None)
        model = embedder.model_version
        self.fingerprint = None
        if (embedder.state == 'ready' and type(self.dimension) is int and 1 <= self.dimension <= 4096
                and isinstance(model, str) and re.fullmatch(r'[a-zA-Z0-9:._-]{1,100}', model)):
            # Production supplies the pinned model manifest and actual tokenizer
            # budget/pooling fingerprint. Test adapters must declare model+dimension.
            self.fingerprint = text_hash(json.dumps({'identity': self.identity,
                'input_contract': 'history-literal-quote-1'}, sort_keys=True))
        self.vectors = {}
        self.pending = set()
        self.hits = self.encoded = 0
        self.write_failures = 0

    def require_current(self, embedder=None):
        if encoder_identity(embedder or self.embedder) != self.identity:
            raise ValueError('history_encoder_changed')

    def encode(self, text):
        self.require_current()
        # Hash exactly what is passed to encode; no trimming/normalization/source hash.
        digest = text_hash(text)
        if self.fingerprint and digest in self.vectors:
            self.hits += 1
            return list(self.vectors[digest]), digest
        if self.fingerprint:
            row = self.db.scalar(select(CaseHistoryVectorReuse).where(
                CaseHistoryVectorReuse.text_sha256 == digest,
                CaseHistoryVectorReuse.encoder_fingerprint == self.fingerprint,
                CaseHistoryVectorReuse.dimension == self.dimension))
            if row is not None and row.model_version == self.embedder.model_version:
                try:
                    vector = normalized_vector(row.embedding, self.dimension)
                    self.vectors[digest] = vector
                    self.hits += 1
                    return list(vector), digest
                except LocalEmbeddingError:
                    # A disposable corrupt vector is recomputed, never delivered.
                    pass
        values = self.embedder.encode(text)
        self.require_current()
        dimension = self.dimension if type(self.dimension) is int else len(values)
        if not 1 <= dimension <= 4096:
            raise LocalEmbeddingError('embedding_invalid_dimension')
        vector = normalized_vector(values, dimension)
        self.encoded += 1
        if self.fingerprint:
            self.vectors[digest] = vector
            self.pending.add(digest)
        return list(vector), digest

    def publish(self, digests):
        self.require_current()
        if not self.fingerprint:
            return
        if self.db.get_bind().dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        keys = sorted(set(digests) & self.pending)
        if not keys:
            return
        # Flush core rows outside the optional cache savepoint: genuine fragment
        # failures must not be mistaken for a harmless reuse-write failure.
        self.db.flush()
        try:
            with self.db.begin_nested():
                for digest in keys:
                    statement = insert(CaseHistoryVectorReuse).values(text_sha256=digest,
                        encoder_fingerprint=self.fingerprint, dimension=self.dimension,
                        model_version=self.embedder.model_version, embedding=self.vectors[digest])
                    self.db.execute(statement.on_conflict_do_update(
                        index_elements=['text_sha256', 'encoder_fingerprint', 'dimension'],
                        set_={'model_version': statement.excluded.model_version,
                              'embedding': statement.excluded.embedding}))
        except SQLAlchemyError:
            # Reuse is disposable; a cache write cannot roll back a core save.
            # Do not log exception text/SQL parameters containing sensitive vectors.
            self.write_failures += 1
        # Keep pending keys until the whole caller transaction finishes: a
        # rolled-back case savepoint must not strand another case's reuse.
