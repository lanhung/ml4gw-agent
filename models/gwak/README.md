# GWAK 2.0 models used by `gwak.scan`

Local TorchScript exports recorded against ML4GW/gwak commit `7b9f58a`.
`MANIFEST.json` pins each file's SHA-256 and the adapter preprocessing;
`gwak.scan` rejects mismatched revisions or hashes. The available SimCLR
training configuration is kept next to the weights.

The manifest's `trained_by` field is an existing attribution, not independently
verified evidence. Training ownership, the NF training configuration, the export
chain and the embedder/metric pairing need Fan / author confirmation. See the
[source review](../../docs/MODEL_PROVENANCE_REVIEW.md). No attribution metadata
was rewritten as part of this review.
