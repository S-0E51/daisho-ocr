# Third-party components and attribution

Daisho is GPL-3.0 (see `LICENSE`). This file records what it builds on.

## The reader — japReader

`study/japReader` is a **fork of [japReader](https://github.com/marisukukise/japReader)**
by marisukukise, itself a continuation of the original by
[seth-js](https://github.com/seth-js/japReader). GPL-3.0.

Our modifications (an OCR bridge, an offline Ichiran backend, a grammar/study
workspace, and the removal of the DeepL and cloud-LLM integrations) are listed
in that submodule's `CHANGES.md`, as GPL-3.0 §5(a) requires.

## Dictionary data — JMdict / EDRDG

Word definitions, part-of-speech tags and the particle sense notes shown in the
reader come from **JMdict**, by way of Ichiran. JMdict is the property of the
**Electronic Dictionary Research and Development Group** and is used in
conformance with the Group's licence (Creative Commons Attribution-ShareAlike).

- <https://www.edrdg.org/jmdict/j_jmdict.html>
- <https://www.edrdg.org/edrdg/licence.html>

## Parsing — Ichiran

Segmentation and morphological analysis come from
**[Ichiran](https://github.com/tshatrov/ichiran)** by tshatrov. Ichiran also
supplies the conjugation data the grammar engine reads to name verb forms and to
decide a particle's role in context.

## Grammar packs

- **Core patterns** and **Particles** — written for this project. GPL-3.0.
- **Hanabira JLPT (N5–N1)** — optional. Grammar points derived from
  [Hanabira's content repository](https://github.com/tristcoil/hanabira.org-japanese-content),
  released under a Creative Commons licence that asks for a link back to
  **[hanabira.org](https://hanabira.org)**. The Options screen shows that credit
  whenever the pack is enabled.
- **Imabi / Tae Kim reference links** — optional. Built from
  [bunpou/japanese-grammar-db](https://github.com/bunpou/japanese-grammar-db)
  (GPL-3.0), which is an index of lesson links rather than a body of grammar
  text. Only the links are bundled.

## Linked, never bundled

These are **all rights reserved**. Daisho links out to them as further reading
and does not copy, redistribute or derive from their text.

- **Imabi** — <https://www.imabi.net/>
- **Pomax, "An Introduction to Japanese"** — <https://pomax.github.io/nrGrammar/>
- **Tae Kim's Guide to Japanese** — <https://guidetojapanese.org/>

## OCR engines

Installed from PyPI at setup time, not bundled here:

- **PaddleOCR** / **PaddlePaddle** (Apache-2.0)
- **manga-ocr** (Apache-2.0) — by kha-white
- **Surya** — GPL-3.0 code, with separate licensing terms for its model weights.
  Optional; not installed unless you choose that engine.
- **RapidOCR** (Apache-2.0) and **ONNX Runtime** (MIT)

Model weights for these are downloaded from their upstream sources on first use
and are subject to their own licences.
