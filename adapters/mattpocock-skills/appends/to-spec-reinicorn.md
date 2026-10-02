## Reinicorn

Specs in a Reinicorn-managed repo are **review-gated** kb docs, not tracker
issues. `rcorn spec create "<title>"` lands the doc under
`kb/{repo}/specs/drafts/` with `status: draft` — leave that status alone.
A human moves it through review; `rcorn review status` lists what is still
open.

A draft spec is not buildable-on. Only once the spec is approved (out of
`drafts/`, `status: approved`) may planning or implementation start from it.
