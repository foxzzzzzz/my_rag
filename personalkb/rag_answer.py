"""Evidence-gated structured answers for the formal RAG index."""
import json
import re
import uuid

from .workflow_store import WorkflowError
from .execution_guard import execution_guard


class AnswerService:
    def __init__(self, store, index, config, provider=None):
        self.store, self.index, self.config, self.provider = store, index, config, provider

    def _generate(self, question, filters, allow_paid, request_id, mode, expected_source_ids):
        if self.config.get('enabled') is not True:
            raise WorkflowError('rag_disabled')
        with execution_guard(self.store):
            if expected_source_ids is not None:
                coverage = self.index.status(filters=filters)
                indexed = set(coverage['indexed_source_ids'])
                if not indexed or indexed != set(coverage['eligible_source_ids']) or indexed != set(expected_source_ids):
                    raise WorkflowError('rag_coverage_changed')
            return self._generate_locked(question, filters, allow_paid, request_id, mode)

    def _generate_locked(self, question, filters, allow_paid, request_id, mode):
        if not isinstance(question, str) or not question.strip() or len(question) > self.config['limits']['max_question_chars']:
            raise WorkflowError('invalid_question')
        if request_id is None:
            request_id = uuid.uuid4().hex
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise WorkflowError('invalid_request_id')
        contexts = self.index.query(question, filters=filters, allow_paid=allow_paid, request_id=request_id + ':query', run_id=request_id, mode=mode)
        contexts = contexts[:self.config['retrieval']['context_k']]
        refusal = {'answer': self.config['refusal_text'], 'citations': [], 'insufficient_evidence': True, 'request_id': request_id}
        if not contexts:
            return refusal, contexts
        self.index.validate_citations(contexts, filters=filters)
        evidence = json.dumps(contexts, ensure_ascii=False)
        if len(evidence.encode('utf-8')) > self.config['limits']['max_context_bytes']:
            raise WorkflowError('context_too_large')
        self.index.validate_citations(contexts, filters=filters)
        if self.provider is None:
            from .rag_provider import RagProvider
            self.provider = RagProvider(self.store, self.config)
        response = self.provider.answer([{'role': 'system', 'content': self.config['answer_system_prompt']}, {'role': 'user', 'content': json.dumps({'question': question, 'evidence': contexts}, ensure_ascii=False)}], allow_paid=allow_paid, request_id=request_id + ':answer', run_id=request_id)
        self.index.validate_citations(contexts, filters=filters)
        try:
            result = json.loads(response['content'])
            if not isinstance(result, dict) or set(result) != {'answer', 'citation_ids', 'insufficient_evidence'}:
                raise ValueError()
            answer, ids, insufficient = result['answer'], result['citation_ids'], result['insufficient_evidence']
            if not isinstance(answer, str) or len(answer) > self.config['limits']['max_answer_chars'] or not isinstance(insufficient, bool) or not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
                raise ValueError()
            if insufficient:
                return refusal, contexts
            by_id = {c['chunk_id']: c for c in contexts}
            if set(re.findall(r'\[([0-9a-fA-F]{64})\]', answer)) != set(ids) or not set(ids) <= set(by_id):
                raise ValueError()
            if not ids or not answer.strip():
                raise ValueError()
            return {'answer': answer, 'citations': [by_id[i] for i in ids], 'insufficient_evidence': False, 'request_id': request_id}, contexts
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise WorkflowError('invalid_model_response') from None

    def ask(self, question, *, filters=None, allow_paid=False, request_id=None, mode=None, expected_source_ids=None):
        result, contexts = self._generate(question, filters, allow_paid, request_id, mode, expected_source_ids)
        if contexts:
            self.index.validate_citations(contexts, filters=filters)
        return result

    def stream(self, question, *, filters=None, allow_paid=False, request_id=None, mode=None, expected_source_ids=None):
        yield {'type': 'progress'}
        contexts = []
        try:
            result, contexts = self._generate(question, filters, allow_paid, request_id, mode, expected_source_ids)
            if contexts:
                self.index.validate_citations(contexts, filters=filters)
            yield {'type': 'answer', **result}
            if contexts:
                self.index.validate_citations(contexts, filters=filters)
            yield {'type': 'done'}
        except WorkflowError as exc:
            if exc.code in ('rag_invalidated', 'rag_rebuild_required'):
                yield {'type': 'invalidated'}
            else:
                yield {'type': 'error', 'code': exc.code}
