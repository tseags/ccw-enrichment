type ReasonedScore = {
  score: number;
  reasons: string[];
};

export function scoreWebsiteConfidence(input: {
  emailDomainMatches: boolean;
  phoneMatchesCountySource: boolean;
  hasConflictingCandidates: boolean;
}): ReasonedScore {
  let score = 0.2;
  const reasons: string[] = [];
  if (input.emailDomainMatches) {
    score += 0.35;
    reasons.push("email_domain_match");
  }
  if (input.phoneMatchesCountySource) {
    score += 0.25;
    reasons.push("phone_match");
  }
  if (input.hasConflictingCandidates) {
    score -= 0.4;
    reasons.push("conflicting_candidates");
  }
  return { score: Math.max(0, Math.min(1, score)), reasons };
}

export function needsReview(confidence: number, hasConflict: boolean) {
  return confidence < 0.6 || hasConflict;
}
