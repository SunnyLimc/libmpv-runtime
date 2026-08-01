import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:media_kit/media_kit.dart';

import 'runtime_gate.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  const url = String.fromEnvironment('LIBMPV_RUNTIME_TEST_URL');
  if (url.isEmpty) {
    stderr.writeln('LIBMPV_RUNTIME_TEST_URL is required');
    exit(64);
  }
  MediaKit.ensureInitialized();
  final player = Player();
  try {
    await player.open(Media(url)).timeout(const Duration(seconds: 20));
    await verifyNativeRuntime(player);
    // `print` is intentionally used so Android forwards the gate marker to logcat.
    print('LIBMPV_RUNTIME_CONSUMER_OK');
    await player.dispose();
    exit(0);
  } catch (error, stackTrace) {
    print('LIBMPV_RUNTIME_CONSUMER_ERROR: $error');
    stderr.writeln(error);
    stderr.writeln(stackTrace);
    await player.dispose();
    exit(1);
  }
}
