# MediaKit consumer gate

This is an actual Flutter consumer, not a mock of the package layout. The
validation workflow generates the selected exact-name drop-in packages under a
platform-specific generated directory, serves the deterministic WAV over HTTP with Range
support, builds the native application, opens the online URL through MediaKit,
sets `af=lavfi=[volume=0.5]` after load, and waits for decoded playback.

The C PCM probe remains the authoritative gain measurement. This fixture proves
that Flutter plugin registration, MediaKit native loading, video integration,
Android JNI helper setup, networking, and the runtime property path all work
together.
