# Relevance audit — annotator 2 instructions

Thanks for helping! This takes about 45–60 minutes, no setup required.

**Task:** you'll judge whether retrieved code examples are relevant to fixing a
given bug. This is a blind audit for a research paper — you won't be told (and
must not try to figure out) which retrieval system produced which example.

**Steps:**

1. Open the attached `audit_annotation_ui.html` in any browser (double-click).
2. Select **ann2** in the dropdown at the top.
3. For each of the 20 tasks: read the **target bug** (buggy code + test-failure
   signal), then for each candidate A–D decide:

   > Would this candidate's buggy→fixed change plausibly guide someone (or an
   > AI) fixing the target bug?

   Click **Relevant (1)** or **Not relevant (0)**. Judge the *repair pattern*
   (what kind of change fixes what kind of problem), not surface similarity —
   similar variable names alone don't make it relevant; the same kind of fix
   for the same kind of failure does.
4. Trust your judgment and don't overthink — genuine disagreement between
   annotators is expected and is itself part of the measurement.
5. Progress saves automatically in your browser. When the counter reads 80/80,
   click **Export JSON** and send back the downloaded `worksheet_ann2.json`.

**Two rules:** work independently — no discussing judgments with anyone until
you've sent the file — and complete it in one browser (progress is stored
locally).
