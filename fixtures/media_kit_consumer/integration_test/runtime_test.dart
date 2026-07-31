import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('loads the promoted runtime and applies an online filter', (tester) async {
    const url = String.fromEnvironment('LIBMPV_RUNTIME_TEST_URL');
    expect(url, isNotEmpty);
    MediaKit.ensureInitialized();
    final player = Player();
    addTearDown(player.dispose);

    await player.open(Media(url)).timeout(const Duration(seconds: 20));
    await player.stream.playing
        .firstWhere((value) => value)
        .timeout(const Duration(seconds: 20));
    final platform = player.platform;
    expect(platform, isA<NativePlayer>());
    await (platform! as NativePlayer)
        .setProperty('af', 'lavfi=[volume=0.5]')
        .timeout(const Duration(seconds: 10));
    final controller = VideoController(player);
    expect(controller, isNotNull);
    await player.stream.completed.firstWhere((value) => value).timeout(
          const Duration(seconds: 30),
        );
    expect(player.state.completed, isTrue);
  });
}
