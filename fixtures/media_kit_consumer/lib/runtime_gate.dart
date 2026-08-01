import 'dart:async';

import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

Future<void> verifyNativeRuntime(
  Player player, {
  bool requirePlaybackClock = true,
}) async {
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

  if (requirePlaybackClock) {
    final deadline = DateTime.now().add(const Duration(seconds: 20));
    var advanced = false;
    while (DateTime.now().isBefore(deadline)) {
      final seconds = double.tryParse(await platform.getProperty('time-pos'));
      if (seconds != null && seconds >= 0.25) {
        advanced = true;
        break;
      }
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    if (!advanced) {
      throw TimeoutException('libmpv playback clock did not advance');
    }
    print('LIBMPV_RUNTIME_CONSUMER_STAGE: clock');
  } else {
    print('LIBMPV_RUNTIME_CONSUMER_STAGE: headless-clock-not-required');
  }

  // Attach the video plugin only after all NativePlayer property reads.
  // MediaKit waits for an attached VideoController to initialize before
  // servicing properties, which cannot complete for this audio-only WAV.
  final controller = VideoController(player);
  if (controller.player != player) {
    throw StateError('VideoController did not retain the MediaKit player');
  }
}
