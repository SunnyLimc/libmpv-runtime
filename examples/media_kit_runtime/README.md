# Using a promotion

Download the exact-name package zip for the target platform from one
`runtime-YYYYMMDD.N` release, extract it into the application's `third_party`
directory, and use a Dart path dependency. Keep the promotion ID with the app's
dependency update so rollback is a normal source-control change.

The executable runtime archive is fetched and SHA-256 verified by the generated
package during the native build. Linux is not downloaded here; install the
distribution's `libmpv.so.2` and build development packages instead.
