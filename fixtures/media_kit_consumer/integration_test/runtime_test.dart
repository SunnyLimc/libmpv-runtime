import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:media_kit/media_kit.dart';
import 'package:libmpv_runtime_consumer/runtime_gate.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('loads the promoted runtime and applies an online filter',
      (tester) async {
    const url = String.fromEnvironment('LIBMPV_RUNTIME_TEST_URL');
    expect(url, isNotEmpty);
    MediaKit.ensureInitialized();
    final player = Player();
    addTearDown(player.dispose);

    await player.open(Media(url)).timeout(const Duration(seconds: 20));
    await verifyNativeRuntime(player);
  });
}
