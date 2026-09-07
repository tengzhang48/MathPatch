# MathPatch

**Precise, auditable editing of equations in Word documents.**

MathPatch reads native Office Math (OMML) out of `.docx` files, represents it, modifies it
under an explicit authorization, writes it back, and proves that nothing else changed.

Its distinctive claim is not conversion:

> **Edit an existing scientific equation safely, rather than regenerate it.**

## MathPatch is

- native Word equation extraction
- semantic equation representation
- controlled equation modification
- OMML generation and patching
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
consuming application. Every entry point takes an already-located `lxml` element and
returns offsets relative to that element; MathPatch never opens a file, resolves a
locator, or sees an object id.

It is designed to be integrated into [ArtifactCert](https://github.com/tengzhang48/ArtifactCert)
as its math capability, while remaining usable on its own.

## Status

Pre-implementation. See **[PLAN.md](PLAN.md)** for the design, the milestones, and the
findings from real manuscripts and real integration code that shape them.

Measure a corpus before trusting any recovery estimate:

```
ARTIFACTCERT_DIR=/path/to/docx tools/corpus_math_inventory.py
```

## License

MIT
