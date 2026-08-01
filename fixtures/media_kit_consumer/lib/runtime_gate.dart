import 'dart:async';

import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

Future<void> verifyNativeRuntime(Player player) async {
  await player.stream.playing
      .firstWhere((value) => value)
      .timeout(const Duration(seconds: 20));
  print('LIBMPV_RUNTIME_CONSUMER_STAGE: playing');
  final platform = player.platform;
  if (platform is! NativePlayer) {
    throw StateError('MediaKit did not create a NativePlayer');
  }
  const filter = 'lavfi=[volume=0.5]';
  await platform.setProperty('af', filter).timeout(const Duration(seconds: 10));
  final appliedFilter =
      await platform.getProperty('af').timeout(const Duration(seconds: 10));
  if (!appliedFilter.contains('volume=0.5')) {
    throw StateError('libmpv did not retain the audio filter: $appliedFilter');
  }
  print('LIBMPV_RUNTIME_CONSUMER_STAGE: filter');
  final controller = VideoController(player);
  if (controller.player != player) {
    throw StateError('VideoController did not retain the MediaKit player');
  }

  final deadline = DateTime.now().add(const Duration(seconds: 20));
  while (DateTime.now().isBefore(deadline)) {
    final seconds = double.tryParse(await platform.getProperty('time-pos'));
    if (seconds != null && seconds >= 0.25) {
      print('LIBMPV_RUNTIME_CONSUMER_STAGE: clock');
      return;
    }
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
  throw TimeoutException('libmpv playback clock did not advance');
}
