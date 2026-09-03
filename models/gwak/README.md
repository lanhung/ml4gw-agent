# GWAK 2.0 models used by `gwak.scan`

TorchScript exports of the user's own GWAK 2.0 training on the CIT LDG
cluster (ML4GW/gwak commit `7b9f58a`). `MANIFEST.json` pins the SHA-256 of
each file and the preprocessing the adapter applies; `gwak.scan` refuses to
run when `model_revision` does not match the manifest or a hash differs.
The training configuration is kept next to the weights for provenance.
