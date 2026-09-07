# MathPatch

**Precise, auditable editing of equations in Word documents.**

The distinctive claim is not conversion:

> **Edit an existing scientific equation safely, rather than regenerate it.**

## What exists today (M0 / M0.1)

- **equation-aware canonical projection** — one traversal of a paragraph yields its canonical
  text and the positions of every math span, so text and offsets cannot disagree
- **protected-span discovery** — outermost-only (an `m:oMathPara` is one span, not two) and by
  descent (math inside a revision wrapper, hyperlink, or run is still found)
- **round-trip-stable digests** — C14N hashes that survive an lxml parse/mutate/reserialize
  cycle, so a protected equation can be *proven* unchanged rather than assumed unchanged

That is a read-only foundation. It does not yet modify an equation.

## Target capability

- native Word equation extraction
- semantic equation representation with **source provenance**
- controlled equation modification under an explicit authorization
- minimum-disturbance OMML patching (mutate the smallest existing node; never regenerate)
- round-trip verification
- change provenance

## MathPatch is not

- a CAS
- an equation OCR system
- a Word replacement
- a general DOCX converter
- a LaTeX editor
- a document locator or object-identity system

## Boundary

MathPatch owns **math representation and serialization**. It does **not** own document
addressing, object identity, authorization, or release decisions — those belong to the
consuming application. Every entry point takes an already-located `lxml` element and returns
offsets relative to that element; MathPatch never opens a file, resolves a locator, or sees an
object id.

It is designed to be integrated into
[ArtifactCert](https://github.com/tengzhang48/ArtifactCert) as its math capability, while
remaining usable on its own.

## Status and evidence

See **[PLAN.md](PLAN.md)** for the design, the milestones, and the findings — from real
manuscripts and from real integration code — that shape them. Findings that turned out to be
wrong are marked RETRACTED there rather than deleted.

`M0_EVIDENCE.json` binds the current claims to exact commits, versions, and per-document
content hashes. To re-derive everything locally:

```
ARTIFACTCERT_DIR=/path/to/manuscripts \
ARTIFACTCERT_PY=/path/to/ArtifactCert/.venv/bin/python \
tools/verify_m0.sh
```

The drift gate needs an importable ArtifactCert because it compares against that project's own
`_para_text`; copying that function here would be the drift the gate exists to detect. CI runs
only the synthetic suite, so a green badge proves internal consistency, not the corpus claims.

## License

MIT — see [LICENSE](LICENSE).
