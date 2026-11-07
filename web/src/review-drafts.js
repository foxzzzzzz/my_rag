import {validReview} from './helpers.js';

const fields = ['score', 'reviewer', 'decision', 'note'];
export function draftKey(sourceId, versionId) {
  return sourceId && versionId ? JSON.stringify([sourceId, versionId]) : '';
}
export function emptyReviewDraft(reviewer = '本人') {
  return {score:'', reviewer, decision:'approve', note:'', saved:null, reviewId:null};
}
export function updateReviewDraft(draft, patch) {
  const changed = fields.some(key => Object.hasOwn(patch, key) && patch[key] !== draft[key]);
  return {...draft, ...patch, reviewId: changed ? null : (Object.hasOwn(patch, 'reviewId') ? patch.reviewId : draft.reviewId)};
}
export function saveReviewDraft(draft) {
  const saved = Object.fromEntries(fields.map(key => [key, String(draft[key])]));
  // An unchanged saved submission may have reached the server despite a lost response.
  return {...draft, saved, reviewId:reviewDraftSaved(draft) ? draft.reviewId : null};
}
export function reviewDraftSaved(draft) {
  return !!draft.saved && fields.every(key => draft.saved[key] === draft[key]);
}
export function canSubmitReview(draft, target) {
  return reviewDraftSaved(draft) && validReview(draft.score, draft.decision, target, draft.reviewer);
}
