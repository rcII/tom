"""R9 ephemeral review panel — spawn one-shot reviewers, reconcile their verdicts.

The pure core: :mod:`tom.review.reconcile` folds N verdicts into one panel
result, and :mod:`tom.review.runner` is the spawn/collect seam the real
SDK-backed agent plugs into. The concurrent ephemeral SDK agents + the NATS
publish are the runtime shell layered on this.
"""
