import { highlightText } from "@/lib/fillers";

/** Renders a transcript with filler words (amber) and quantified impact (green) highlighted. */
export default function TranscriptText({ text }: { text: string }) {
  const segments = highlightText(text);
  return (
    <>
      {segments.map((seg, i) =>
        seg.filler ? (
          <mark className="filler-mark" title={"Filler: " + seg.filler} key={i}>
            {seg.text}
          </mark>
        ) : seg.impact ? (
          <mark className="impact-mark" title="Quantified impact" key={i}>
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  );
}
