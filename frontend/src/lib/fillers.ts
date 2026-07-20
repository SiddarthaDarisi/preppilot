/**
 * Filler-word highlighting for transcripts. Ports the detection semantics of
 * backend/analytics/fillers.py so the marks the user sees match the counts the
 * backend feeds into metrics/coaching. Keep the two in sync.
 */

export interface TextSegment {
  text: string;
  /** canonical filler name (e.g. "um", "you know") or null for plain text */
  filler: string | null;
  /** quantified-impact mark (numbers/%/durations/money) — see highlightImpact */
  impact?: boolean;
}

// Quantified impact: numbers/percents/durations/money/scale — the same signal
// Google Interview Warmup calls out as "talking points" that make an answer
// concrete. Pure client-side regex, no backend involvement.
const IMPACT_PATTERN =
  /\$\s?\d[\d,]*(\.\d+)?[kKmMbB]?|\b\d[\d,]*(\.\d+)?\s*(%|percent|x|ms|s|sec|secs|seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?|users?|customers?|qps|rps|tps|k|m|million|billion)\b/gi;

export function highlightImpact(text: string): TextSegment[] {
  if (!text) return [];
  const segments: TextSegment[] = [];
  let cursor = 0;
  IMPACT_PATTERN.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = IMPACT_PATTERN.exec(text)) !== null) {
    if (m.index > cursor) segments.push({ text: text.slice(cursor, m.index), filler: null });
    segments.push({ text: m[0], filler: null, impact: true });
    cursor = m.index + m[0].length;
    if (m.index === IMPACT_PATTERN.lastIndex) IMPACT_PATTERN.lastIndex++;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), filler: null });
  return segments;
}

/** Fillers take priority (they're already exclusion-checked); impact marks
 * are then layered onto whatever text is left over. */
export function highlightText(text: string): TextSegment[] {
  const fillerSegs = highlightFillers(text);
  const out: TextSegment[] = [];
  for (const seg of fillerSegs) {
    if (seg.filler) {
      out.push(seg);
      continue;
    }
    out.push(...highlightImpact(seg.text));
  }
  return out;
}

interface Range {
  start: number;
  end: number;
  name: string;
}

// name -> global regex. "so" and "like" need special handling (below).
const PATTERNS: [string, RegExp][] = [
  ["um", /\bum+\b/gi],
  ["uh", /\buh+\b/gi],
  ["er", /\ber+\b/gi],
  ["ah", /\bah+\b/gi],
  ["hmm", /\bhm+\b/gi],
  ["you know", /\byou\s+know\b/gi],
  ["sort of", /\bsort\s+of\b/gi],
  ["kind of", /\bkind\s+of\b/gi],
  ["i mean", /\bi\s+mean\b/gi],
  ["basically", /\bbasically\b/gi],
  ["actually", /\bactually\b/gi],
  ["right", /\bright\s*\?/gi],
];

// sentence-initial "so": start of text/line or right after . ! ? — marked so
// that only the word "so" (not the leading punctuation/space) is highlighted.
const SO_PATTERN = /(?:(?<=[.!?])\s*|^\s*)so\b/gim;

// Words that, immediately before "like", mark a legitimate (non-filler) use.
// Copied verbatim from _LIKE_EXCLUDE_BEFORE in the backend.
const LIKE_EXCLUDE_BEFORE = new Set([
  "feel", "feels", "felt", "feeling",
  "look", "looks", "looked", "looking",
  "sound", "sounds", "sounded", "sounding",
  "seem", "seems", "seemed",
  "is", "was", "are", "were", "am", "be", "been", "being",
  "it's", "that's", "he's", "she's", "there's", "what's",
  "would", "'d", "d",
  "just", "much", "more", "something", "anything", "nothing",
]);

const WORD_RE = /[a-z']+/g;

function collectLikeRanges(text: string): Range[] {
  const lower = text.toLowerCase();
  const tokens: { word: string; start: number; end: number }[] = [];
  let m: RegExpExecArray | null;
  WORD_RE.lastIndex = 0;
  while ((m = WORD_RE.exec(lower)) !== null) {
    tokens.push({ word: m[0], start: m.index, end: m.index + m[0].length });
  }
  const ranges: Range[] = [];
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].word !== "like") continue;
    const prev = i > 0 ? tokens[i - 1].word : "";
    if (!LIKE_EXCLUDE_BEFORE.has(prev)) {
      ranges.push({ start: tokens[i].start, end: tokens[i].end, name: "like" });
    }
  }
  return ranges;
}

export function highlightFillers(text: string): TextSegment[] {
  if (!text) return [];

  const ranges: Range[] = [];
  for (const [name, re] of PATTERNS) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      ranges.push({ start: m.index, end: m.index + m[0].length, name });
      if (m.index === re.lastIndex) re.lastIndex++; // guard against zero-width
    }
  }

  // "so": shrink the match to just the word (skip leading whitespace).
  SO_PATTERN.lastIndex = 0;
  let sm: RegExpExecArray | null;
  while ((sm = SO_PATTERN.exec(text)) !== null) {
    const soStart = sm.index + sm[0].toLowerCase().lastIndexOf("so");
    ranges.push({ start: soStart, end: soStart + 2, name: "so" });
    if (sm.index === SO_PATTERN.lastIndex) SO_PATTERN.lastIndex++;
  }

  ranges.push(...collectLikeRanges(text));

  // Sort by start, then drop any range that overlaps an already-kept one.
  ranges.sort((a, b) => a.start - b.start || b.end - a.end);
  const kept: Range[] = [];
  let lastEnd = -1;
  for (const r of ranges) {
    if (r.start >= lastEnd) {
      kept.push(r);
      lastEnd = r.end;
    }
  }

  // Emit segments.
  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const r of kept) {
    if (r.start > cursor) segments.push({ text: text.slice(cursor, r.start), filler: null });
    segments.push({ text: text.slice(r.start, r.end), filler: r.name });
    cursor = r.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), filler: null });
  return segments;
}
