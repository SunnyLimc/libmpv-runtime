import 'dart:io';

import 'package:flutter/widgets.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

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
    await player.stream.playing
        .firstWhere((value) => value)
        .timeout(const Duration(seconds: 20));
    final platform = player.platform;
    if (platform is! NativePlayer) {
      throw StateError('MediaKit did not create a NativePlayer');
    }
    await platform
        .setProperty('af', 'lavfi=[volume=0.5]')
        .timeout(const Duration(seconds: 10));
    final controller = VideoController(player);
    if (controller.player != player) {
      throw StateError('VideoController did not retain the MediaKit player');
    }
    await player.stream.completed
        .firstWhere((value) => value)
        .timeout(const Duration(seconds: 30));
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
