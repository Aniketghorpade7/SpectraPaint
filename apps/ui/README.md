# ui — React renderer

Talks only to the inference service HTTP contract. Holds no Node or filesystem access.

Surfaces: Boot, Bundles, Consultation (with the Catalogue panel), Storage, Settings.

Requests a ~1 MP preview per Shade change while browsing; full resolution only on save or export.
See the latency evidence in [spikes/latency/RESULTS.md](../../spikes/latency/RESULTS.md).
